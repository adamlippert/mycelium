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
