package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// fakeCdn serves the golden blob with single-range support, like TorBox's CDN.
func fakeCdn(t *testing.T, blob []byte) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		rangeHdr := r.Header.Get("Range")
		if rangeHdr == "" {
			w.Write(blob)
			return
		}
		start, end, err := parseByteRange(rangeHdr, uint64(len(blob)))
		if err != nil {
			w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
			return
		}
		if end > uint64(len(blob)-1) {
			end = uint64(len(blob) - 1)
		}
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, len(blob)))
		w.WriteHeader(http.StatusPartialContent)
		w.Write(blob[start : end+1])
	}))
}

func testFront(t *testing.T, resolveJSON func(cdnURL string) string) (*httptest.Server, *httptest.Server) {
	t.Helper()
	blob, err := os.ReadFile("testdata/cdn.bin")
	if err != nil {
		t.Fatalf("read blob: %v", err)
	}
	cdn := fakeCdn(t, blob)
	t.Cleanup(cdn.Close)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/internal/stream-resolve/") {
			w.Header().Set("Content-Type", "application/json")
			io.WriteString(w, resolveJSON(cdn.URL))
			return
		}
		w.Header().Set("X-Upstream", "flask")
		io.WriteString(w, "proxied:"+r.URL.Path)
	}))
	t.Cleanup(upstream.Close)

	streamer := newStreamer(upstream.URL)
	front := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/internal/") {
			http.NotFound(w, r)
			return
		}
		if token, ok := strings.CutPrefix(r.URL.Path, "/spore-stream/"); ok && token != "" {
			streamer.serve(w, r, token)
			return
		}
		// The real front uses httputil.ReverseProxy here; these tests cover
		// the streaming handler, not the proxy plumbing.
		http.NotFound(w, r)
	}))
	t.Cleanup(front.Close)
	return front, upstream
}

func TestWarmStreamServesTheVirtualLayoutOverHTTP(t *testing.T) {
	front, _ := testFront(t, func(cdnURL string) string {
		return fmt.Sprintf(`{"mode":"warm","cdn_url":"%s","cdn_size":1000,"fsh_path":"testdata/sample.fsh"}`, cdnURL)
	})
	info, _ := loadFsh("testdata/sample.fsh")
	blob, _ := os.ReadFile("testdata/cdn.bin")

	req, _ := http.NewRequest("GET", front.URL+"/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=10-200")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusPartialContent {
		t.Fatalf("status %d, want 206", resp.StatusCode)
	}
	if cr := resp.Header.Get("Content-Range"); cr != "bytes 10-200/1000" {
		t.Fatalf("Content-Range %q", cr)
	}
	body, _ := io.ReadAll(resp.Body)
	want := serveVirtual(info, blob, 10, 200)
	if string(body) != string(want) {
		t.Fatalf("body mismatch: %d bytes, want %d", len(body), len(want))
	}
}

func TestColdStreamPassesRangesThrough(t *testing.T) {
	front, _ := testFront(t, func(cdnURL string) string {
		return fmt.Sprintf(`{"mode":"cold","cdn_url":"%s","size":1000}`, cdnURL)
	})
	blob, _ := os.ReadFile("testdata/cdn.bin")

	req, _ := http.NewRequest("GET", front.URL+"/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=-100")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusPartialContent {
		t.Fatalf("status %d, want 206", resp.StatusCode)
	}
	body, _ := io.ReadAll(resp.Body)
	if string(body) != string(blob[900:]) {
		t.Fatalf("suffix range served %d bytes, want last 100", len(body))
	}
}

func TestRedirectModeIssues302(t *testing.T) {
	front, _ := testFront(t, func(cdnURL string) string {
		return fmt.Sprintf(`{"mode":"redirect","url":"%s/file.mkv"}`, cdnURL)
	})
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}}
	resp, err := client.Get(front.URL + "/spore-stream/sample")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusFound {
		t.Fatalf("status %d, want 302", resp.StatusCode)
	}
	if loc := resp.Header.Get("Location"); !strings.HasSuffix(loc, "/file.mkv") {
		t.Fatalf("Location %q", loc)
	}
}

func TestUnsatisfiableRangeIs416(t *testing.T) {
	front, _ := testFront(t, func(cdnURL string) string {
		return fmt.Sprintf(`{"mode":"cold","cdn_url":"%s","size":1000}`, cdnURL)
	})
	req, _ := http.NewRequest("GET", front.URL+"/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=5000-")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusRequestedRangeNotSatisfiable {
		t.Fatalf("status %d, want 416", resp.StatusCode)
	}
}

func TestHeadRequestSendsHeadersOnly(t *testing.T) {
	front, _ := testFront(t, func(cdnURL string) string {
		return fmt.Sprintf(`{"mode":"cold","cdn_url":"%s","size":1000}`, cdnURL)
	})
	resp, err := http.Head(front.URL + "/spore-stream/sample")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d, want 200", resp.StatusCode)
	}
	if cl := resp.Header.Get("Content-Length"); cl != "1000" {
		t.Fatalf("Content-Length %q, want 1000", cl)
	}
	body, _ := io.ReadAll(resp.Body)
	if len(body) != 0 {
		t.Fatalf("HEAD returned %d body bytes", len(body))
	}
}

func TestResolveFailurePropagatesStatus(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		io.WriteString(w, `{"error":"materialize failed"}`)
	}))
	defer upstream.Close()
	streamer := newStreamer(upstream.URL)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/spore-stream/deadbeef", nil)
	streamer.serve(rec, req, "deadbeef")
	if rec.Code != http.StatusNotFound {
		t.Fatalf("status %d, want 404", rec.Code)
	}
}

// ── failure modes found by the live load test ────────────────────────────────

// rateLimitedCdn always answers 429, like TorBox's CDN under a burst.
func rateLimitedCdn(t *testing.T) *httptest.Server {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
		io.WriteString(w, "rate limited")
	}))
	t.Cleanup(srv.Close)
	return srv
}

func TestColdStreamAnswers503WhenTheCdnIsRateLimited(t *testing.T) {
	// The old shape wrote 206 headers first and then truncated at zero
	// bytes, which Cloudflare surfaced as 520s and players as corrupt
	// files. The status must now arrive before any success headers.
	cdn := rateLimitedCdn(t)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, fmt.Sprintf(`{"mode":"cold","cdn_url":"%s","size":1000}`, cdn.URL))
	}))
	defer upstream.Close()
	streamer := newStreamer(upstream.URL)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=0-")
	streamer.serve(rec, req, "sample")

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d, want 503", rec.Code)
	}
	if ra := rec.Header().Get("Retry-After"); ra == "" {
		t.Fatal("503 without Retry-After")
	}
	if cr := rec.Header().Get("Content-Range"); cr != "" {
		t.Fatalf("success header Content-Range %q leaked into the error", cr)
	}
}

func TestWarmSeekPastHeaderAnswers503WhenTheCdnIsRateLimited(t *testing.T) {
	// A seek whose first byte comes from the CDN must also fail with a
	// status, not a truncated 206.
	cdn := rateLimitedCdn(t)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, fmt.Sprintf(
			`{"mode":"warm","cdn_url":"%s","cdn_size":1000,"fsh_path":"testdata/sample.fsh"}`, cdn.URL))
	}))
	defer upstream.Close()
	streamer := newStreamer(upstream.URL)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=500-999") // entirely past the 116-byte cached header
	streamer.serve(rec, req, "sample")

	if rec.Code != http.StatusServiceUnavailable {
		t.Fatalf("status %d, want 503", rec.Code)
	}
}

func TestWarmRangeInsideTheCachedHeaderServesEvenWithTheCdnDown(t *testing.T) {
	// The header lives on local disk; a range inside it must not depend on
	// the CDN at all.
	cdn := rateLimitedCdn(t)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, fmt.Sprintf(
			`{"mode":"warm","cdn_url":"%s","cdn_size":1000,"fsh_path":"testdata/sample.fsh"}`, cdn.URL))
	}))
	defer upstream.Close()
	info, _ := loadFsh("testdata/sample.fsh")
	streamer := newStreamer(upstream.URL)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest("GET", "/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=0-99")
	streamer.serve(rec, req, "sample")

	if rec.Code != http.StatusPartialContent {
		t.Fatalf("status %d, want 206", rec.Code)
	}
	if got, want := rec.Body.String(), string(info.Header[0:100]); got != want {
		t.Fatalf("body mismatch: %d bytes", len(rec.Body.Bytes()))
	}
}

func TestColdStreamResumesAfterAMidStreamCdnDrop(t *testing.T) {
	// First CDN response dies after 100 bytes; the retry must resume from
	// byte 100 and the client must still receive the exact full range.
	blob, err := os.ReadFile("testdata/cdn.bin")
	if err != nil {
		t.Fatal(err)
	}
	var calls int
	cdn := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		start, end, perr := parseByteRange(r.Header.Get("Range"), uint64(len(blob)))
		if perr != nil {
			w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
			return
		}
		data := blob[start : end+1]
		if calls == 1 && len(data) > 100 {
			data = data[:100] // lie about length, then die: a dropped transfer
		}
		w.Header().Set("Content-Range", fmt.Sprintf("bytes %d-%d/%d", start, end, len(blob)))
		w.Header().Set("Content-Length", fmt.Sprint(end-start+1))
		w.WriteHeader(http.StatusPartialContent)
		w.Write(data)
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
	}))
	defer cdn.Close()
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, fmt.Sprintf(`{"mode":"cold","cdn_url":"%s","size":1000}`, cdn.URL))
	}))
	defer upstream.Close()

	streamer := newStreamer(upstream.URL)
	front := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		streamer.serve(w, r, "sample")
	}))
	defer front.Close()

	req, _ := http.NewRequest("GET", front.URL+"/spore-stream/sample", nil)
	req.Header.Set("Range", "bytes=200-899")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if string(body) != string(blob[200:900]) {
		t.Fatalf("resumed body wrong: got %d bytes, want %d (cdn calls=%d)",
			len(body), 700, calls)
	}
	if calls < 2 {
		t.Fatalf("expected a resume fetch, cdn saw %d call(s)", calls)
	}
}
