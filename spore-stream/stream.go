package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// resolveResult is /internal/stream-resolve's answer: what to serve and from
// where. Python makes the decision; we move the bytes.
type resolveResult struct {
	Mode    string `json:"mode"` // "redirect" | "cold" | "warm"
	URL     string `json:"url"`  // redirect target
	CdnURL  string `json:"cdn_url"`
	Size    uint64 `json:"size"`     // cold: file size
	CdnSize uint64 `json:"cdn_size"` // warm: virtual/CDN file size
	FshPath string `json:"fsh_path"` // warm: .fsh cache file to serve from
	Error   string `json:"error"`
}

type streamer struct {
	upstream string
	// materialize can legitimately take ~45s (on-play TorBox wait); the rest
	// of the budget covers scraping ahead of the add.
	resolveClient *http.Client
	cdnClient     *http.Client
}

func newStreamer(upstream string) *streamer {
	return &streamer{
		upstream:      strings.TrimRight(upstream, "/"),
		resolveClient: &http.Client{Timeout: 180 * time.Second},
		// No overall timeout: a single CDN Range request serves a stream for
		// as long as the client keeps reading. Header timeout only.
		cdnClient: &http.Client{Transport: &http.Transport{
			ResponseHeaderTimeout: 60 * time.Second,
			MaxIdleConnsPerHost:   32,
			IdleConnTimeout:       90 * time.Second,
		}},
	}
}

func (s *streamer) resolve(token string) (*resolveResult, int, error) {
	resp, err := s.resolveClient.Get(s.upstream + "/internal/stream-resolve/" + token)
	if err != nil {
		return nil, http.StatusBadGateway, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, http.StatusBadGateway, err
	}
	var res resolveResult
	if err := json.Unmarshal(body, &res); err != nil {
		return nil, http.StatusBadGateway, fmt.Errorf("bad resolve payload: %w", err)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, resp.StatusCode, fmt.Errorf("resolve %d: %s", resp.StatusCode, res.Error)
	}
	return &res, http.StatusOK, nil
}

func (s *streamer) serve(w http.ResponseWriter, r *http.Request, token string) {
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		w.Header().Set("Allow", "GET, HEAD")
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	started := time.Now()
	res, status, err := s.resolve(token)
	if err != nil {
		log.Printf("stream: resolve failed token=%s: %v (%.1fs)", token, err, time.Since(started).Seconds())
		http.Error(w, "stream unavailable", status)
		return
	}

	switch res.Mode {
	case "redirect":
		log.Printf("stream: token=%s redirect to CDN", token)
		http.Redirect(w, r, res.URL, http.StatusFound)
	case "cold":
		s.serveCold(w, r, token, res.CdnURL, res.Size)
	case "warm":
		s.serveWarm(w, r, token, res)
	default:
		log.Printf("stream: token=%s unknown mode %q", token, res.Mode)
		http.Error(w, "stream unavailable", http.StatusBadGateway)
	}
}

// parseByteRange mirrors app.py's _parse_byte_range: one RFC 7233 range in
// the forms "start-end", "start-" and the suffix form "-N".
func parseByteRange(rangeHdr string, fileSize uint64) (uint64, uint64, error) {
	_, spec, ok := strings.Cut(rangeHdr, "=")
	if !ok {
		return 0, 0, fmt.Errorf("no = in range %q", rangeHdr)
	}
	startS, endS, ok := strings.Cut(spec, "-")
	if !ok {
		return 0, 0, fmt.Errorf("no - in range %q", rangeHdr)
	}
	var start, end uint64
	if startS == "" {
		if endS == "" {
			return 0, 0, fmt.Errorf("empty range %q", rangeHdr)
		}
		suffixLen, err := strconv.ParseUint(endS, 10, 64)
		if err != nil {
			return 0, 0, err
		}
		if suffixLen > fileSize {
			start = 0
		} else {
			start = fileSize - suffixLen
		}
		end = fileSize - 1
	} else {
		var err error
		start, err = strconv.ParseUint(startS, 10, 64)
		if err != nil {
			return 0, 0, err
		}
		if endS == "" {
			end = fileSize - 1
		} else {
			end, err = strconv.ParseUint(endS, 10, 64)
			if err != nil {
				return 0, 0, err
			}
		}
	}
	if start >= fileSize || start > end {
		return 0, 0, fmt.Errorf("unsatisfiable range %q for size %d", rangeHdr, fileSize)
	}
	return start, end, nil
}

// rangeForRequest resolves the request's Range header against fileSize and
// writes the response status plus streaming headers. Returns ok=false after
// answering 416 itself.
func rangeForRequest(w http.ResponseWriter, r *http.Request, fileSize uint64) (start, end uint64, ok bool) {
	status := http.StatusOK
	start, end = uint64(0), fileSize-1
	if rangeHdr := r.Header.Get("Range"); rangeHdr != "" {
		var err error
		start, end, err = parseByteRange(rangeHdr, fileSize)
		if err != nil {
			w.Header().Set("Content-Range", fmt.Sprintf("bytes */%d", fileSize))
			http.Error(w, "range not satisfiable", http.StatusRequestedRangeNotSatisfiable)
			return 0, 0, false
		}
		if end > fileSize-1 {
			end = fileSize - 1
		}
		status = http.StatusPartialContent
	}
	w.Header().Set("Content-Type", "video/mp4")
	w.Header().Set("Accept-Ranges", "bytes")
	w.Header().Set("Content-Length", strconv.FormatUint(end-start+1, 10))
	if status == http.StatusPartialContent {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, fileSize))
	}
	w.WriteHeader(status)
	return start, end, true
}

func (s *streamer) serveCold(w http.ResponseWriter, r *http.Request, token, cdnURL string, fileSize uint64) {
	if fileSize == 0 {
		http.Error(w, "stream unavailable", http.StatusBadGateway)
		return
	}
	start, end, ok := rangeForRequest(w, r, fileSize)
	if !ok || r.Method == http.MethodHead {
		return
	}
	sent := s.copyCdnRange(w, cdnURL, start, end)
	log.Printf("stream: token=%s cold bytes=%d-%d/%d sent=%d ua=%q",
		token, start, end, fileSize, sent, trunc(r.UserAgent(), 80))
}

func (s *streamer) serveWarm(w http.ResponseWriter, r *http.Request, token string, res *resolveResult) {
	info, err := loadFsh(res.FshPath)
	if err != nil || info.alreadyFast() {
		// The .fsh vanished (or degenerated) between resolve and now; the
		// cold passthrough serves the same bytes the client expects.
		if res.CdnSize > 0 {
			s.serveCold(w, r, token, res.CdnURL, res.CdnSize)
			return
		}
		log.Printf("stream: token=%s fsh load failed: %v", token, err)
		http.Error(w, "stream unavailable", http.StatusBadGateway)
		return
	}
	fileSize := info.CdnSize
	start, end, ok := rangeForRequest(w, r, fileSize)
	if !ok || r.Method == http.MethodHead {
		return
	}
	started := time.Now()
	var sent int64
	for _, reg := range info.virtualRegions(start, end) {
		if reg.FromHeader {
			n, err := w.Write(info.Header[reg.HdrStart : reg.HdrEnd+1])
			sent += int64(n)
			if err != nil {
				return // client went away
			}
			continue
		}
		n := s.copyCdnRange(w, res.CdnURL, reg.CdnStart, reg.CdnEnd)
		sent += n
		if n < int64(reg.CdnEnd-reg.CdnStart+1) {
			break // CDN error or client hung up; stop like the Python path does
		}
	}
	log.Printf("stream: token=%s warm bytes=%d-%d/%d sent=%d (%.1fs) ua=%q",
		token, start, end, fileSize, sent, time.Since(started).Seconds(), trunc(r.UserAgent(), 80))
}

// copyCdnRange streams CDN bytes [start, end] to w, resuming from the
// current position on transient errors (429 with backoff, dropped
// connections) up to a small retry budget. Returns bytes written.
func (s *streamer) copyCdnRange(w io.Writer, cdnURL string, start, end uint64) int64 {
	const maxAttempts = 3
	var written int64
	pos := start
	for attempt := 0; attempt < maxAttempts && pos <= end; attempt++ {
		n, err := s.copyOnce(w, cdnURL, pos, end)
		written += n
		pos += uint64(n)
		if pos > end || err == nil {
			return written
		}
		if errors.Is(err, errClientGone) {
			return written
		}
		var rl *rateLimitedError
		if errors.As(err, &rl) {
			time.Sleep(time.Duration(300*(1<<attempt)) * time.Millisecond)
		}
		log.Printf("stream: cdn error at %d (attempt %d): %v", pos, attempt+1, err)
	}
	return written
}

type rateLimitedError struct{}

func (*rateLimitedError) Error() string { return "cdn 429" }

// errClientGone marks a write failure toward the client: not retryable.
var errClientGone = errors.New("client write failed")

func (s *streamer) copyOnce(w io.Writer, cdnURL string, start, end uint64) (int64, error) {
	req, err := http.NewRequest(http.MethodGet, cdnURL, nil)
	if err != nil {
		return 0, err
	}
	req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end))
	resp, err := s.cdnClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusTooManyRequests {
		return 0, &rateLimitedError{}
	}
	if resp.StatusCode != http.StatusPartialContent && resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("cdn status %d", resp.StatusCode)
	}
	var written int64
	buf := make([]byte, 256*1024)
	body := io.LimitReader(resp.Body, int64(end-start+1))
	for {
		nr, rerr := body.Read(buf)
		if nr > 0 {
			nw, werr := w.Write(buf[:nr])
			written += int64(nw)
			if werr != nil {
				return written, errClientGone
			}
		}
		if rerr == io.EOF {
			return written, nil
		}
		if rerr != nil {
			return written, rerr
		}
	}
}

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
