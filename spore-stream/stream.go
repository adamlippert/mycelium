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

// reportEgress tells Python how many bytes this stream actually served, so
// monthly usage can be measured against the provider's bandwidth floor.
// Fire and forget: a failed report must never affect playback.
func (s *streamer) reportEgress(token string, sent int64) {
	if sent <= 0 {
		return
	}
	body := strings.NewReader(fmt.Sprintf(`{"bytes":%d}`, sent))
	req, err := http.NewRequest(http.MethodPost,
		s.upstream+"/internal/stream-report/"+token, body)
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := s.resolveClient.Do(req)
	if err != nil {
		log.Printf("stream: egress report failed for %s: %v", token, err)
		return
	}
	if resp.StatusCode >= 300 {
		log.Printf("stream: egress report for %s rejected with HTTP %d", token, resp.StatusCode)
	}
	resp.Body.Close()
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

// parseRequestRange resolves the request's Range header against fileSize.
// Returns ok=false after answering 416 itself. Writes NO success headers:
// those wait until the first byte source is secured, so a dead-on-arrival
// stream can still become an honest error status.
func parseRequestRange(w http.ResponseWriter, r *http.Request, fileSize uint64) (start, end uint64, status int, ok bool) {
	status = http.StatusOK
	start, end = uint64(0), fileSize-1
	if rangeHdr := r.Header.Get("Range"); rangeHdr != "" {
		var err error
		start, end, err = parseByteRange(rangeHdr, fileSize)
		if err != nil {
			w.Header().Set("Content-Range", fmt.Sprintf("bytes */%d", fileSize))
			http.Error(w, "range not satisfiable", http.StatusRequestedRangeNotSatisfiable)
			return 0, 0, 0, false
		}
		if end > fileSize-1 {
			end = fileSize - 1
		}
		status = http.StatusPartialContent
	}
	return start, end, status, true
}

func writeStreamHeaders(w http.ResponseWriter, status int, start, end, fileSize uint64) {
	w.Header().Set("Content-Type", "video/mp4")
	w.Header().Set("Accept-Ranges", "bytes")
	w.Header().Set("Content-Length", strconv.FormatUint(end-start+1, 10))
	if status == http.StatusPartialContent {
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, fileSize))
	}
	w.WriteHeader(status)
}

// writeCdnFailure answers a stream whose FIRST CDN fetch failed, before any
// response headers went out: 503 for a rate limit (retryable, and players
// understand a status where they cannot understand a truncated 206), 502
// for anything else. Behind Cloudflare the old truncated-206 shape showed
// up as 520s; without it, as "corrupt file" player errors.
func writeCdnFailure(w http.ResponseWriter, token string, err error) {
	var rl *rateLimitedError
	if errors.As(err, &rl) {
		w.Header().Set("Retry-After", "2")
		http.Error(w, "upstream rate limited", http.StatusServiceUnavailable)
	} else {
		http.Error(w, "upstream error", http.StatusBadGateway)
	}
	log.Printf("stream: token=%s failed before first byte: %v", token, err)
}

func (s *streamer) serveCold(w http.ResponseWriter, r *http.Request, token, cdnURL string, fileSize uint64) {
	if fileSize == 0 {
		http.Error(w, "stream unavailable", http.StatusBadGateway)
		return
	}
	start, end, status, ok := parseRequestRange(w, r, fileSize)
	if !ok {
		return
	}
	if r.Method == http.MethodHead {
		writeStreamHeaders(w, status, start, end, fileSize)
		return
	}
	body, err := s.openCdnRange(cdnURL, start, end)
	if err != nil {
		writeCdnFailure(w, token, err)
		return
	}
	writeStreamHeaders(w, status, start, end, fileSize)
	sent, _ := s.serveCdnSpan(w, cdnURL, start, end, body)
	log.Printf("stream: token=%s cold bytes=%d-%d/%d sent=%d ua=%q",
		token, start, end, fileSize, sent, trunc(r.UserAgent(), 80))
	go s.reportEgress(token, sent)
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
	start, end, status, ok := parseRequestRange(w, r, fileSize)
	if !ok {
		return
	}
	if r.Method == http.MethodHead {
		writeStreamHeaders(w, status, start, end, fileSize)
		return
	}
	regions := info.virtualRegions(start, end)
	// When the very first byte comes from the CDN (a seek past the cached
	// header), secure it before any headers go out. A range starting inside
	// the cached header can always answer, so headers are safe immediately.
	var firstBody io.ReadCloser
	if len(regions) > 0 && !regions[0].FromHeader {
		firstBody, err = s.openCdnRange(res.CdnURL, regions[0].CdnStart, regions[0].CdnEnd)
		if err != nil {
			writeCdnFailure(w, token, err)
			return
		}
	}
	writeStreamHeaders(w, status, start, end, fileSize)
	started := time.Now()
	var sent int64
	for i, reg := range regions {
		if reg.FromHeader {
			n, werr := w.Write(info.Header[reg.HdrStart : reg.HdrEnd+1])
			sent += int64(n)
			if werr != nil {
				return // client went away
			}
			continue
		}
		var pre io.ReadCloser
		if i == 0 {
			pre = firstBody
		}
		n, complete := s.serveCdnSpan(w, res.CdnURL, reg.CdnStart, reg.CdnEnd, pre)
		sent += n
		if !complete {
			break // CDN gave up or client hung up; stop like the Python path does
		}
	}
	log.Printf("stream: token=%s warm bytes=%d-%d/%d sent=%d (%.1fs) ua=%q",
		token, start, end, fileSize, sent, time.Since(started).Seconds(), trunc(r.UserAgent(), 80))
	go s.reportEgress(token, sent)
}

// openCdnRange opens CDN bytes [start, end] WITHOUT writing anything to the
// client, retrying rate limits and transport errors with backoff. Securing
// the source before response headers go out is what turns a dead-on-arrival
// stream into an honest 502/503 instead of a 206 that truncates at zero.
func (s *streamer) openCdnRange(cdnURL string, start, end uint64) (io.ReadCloser, error) {
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			time.Sleep(time.Duration(300*(1<<(attempt-1))) * time.Millisecond)
		}
		req, err := http.NewRequest(http.MethodGet, cdnURL, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end))
		resp, err := s.cdnClient.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		switch {
		case resp.StatusCode == http.StatusTooManyRequests:
			resp.Body.Close()
			lastErr = &rateLimitedError{}
		case resp.StatusCode != http.StatusPartialContent && resp.StatusCode != http.StatusOK:
			resp.Body.Close()
			return nil, fmt.Errorf("cdn status %d", resp.StatusCode)
		default:
			return resp.Body, nil
		}
	}
	return nil, lastErr
}

// serveCdnSpan streams CDN bytes [start, end] to w, starting from body when
// the caller already opened it, resuming from the current position on
// transient errors. Returns bytes written and whether the span completed.
func (s *streamer) serveCdnSpan(w io.Writer, cdnURL string, start, end uint64, body io.ReadCloser) (int64, bool) {
	var sent uint64
	if body != nil {
		n, serr := streamBody(w, body, end-start+1)
		body.Close()
		sent += n
		if errors.Is(serr, errClientGone) {
			return int64(sent), false
		}
	}
	const maxResumes = 3
	for attempt := 0; attempt < maxResumes && start+sent <= end; attempt++ {
		nb, err := s.openCdnRange(cdnURL, start+sent, end)
		if err != nil {
			log.Printf("stream: cdn open failed at %d: %v", start+sent, err)
			return int64(sent), false
		}
		n, serr := streamBody(w, nb, end-(start+sent)+1)
		nb.Close()
		sent += n
		if errors.Is(serr, errClientGone) {
			return int64(sent), false
		}
		if serr != nil {
			log.Printf("stream: cdn error at %d (resume %d): %v", start+sent, attempt+1, serr)
		}
	}
	return int64(sent), start+sent > end
}

// streamBody copies up to max bytes from body to w. A write error means the
// client went away (errClientGone); a read error is a CDN drop the caller
// may resume from.
func streamBody(w io.Writer, body io.Reader, max uint64) (uint64, error) {
	var written uint64
	buf := make([]byte, 256*1024)
	lr := io.LimitReader(body, int64(max))
	for {
		nr, rerr := lr.Read(buf)
		if nr > 0 {
			nw, werr := w.Write(buf[:nr])
			written += uint64(nw)
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

type rateLimitedError struct{}

func (*rateLimitedError) Error() string { return "cdn 429" }

// errClientGone marks a write failure toward the client: not retryable.
var errClientGone = errors.New("client write failed")

func trunc(s string, n int) string {
	if len(s) > n {
		return s[:n]
	}
	return s
}
