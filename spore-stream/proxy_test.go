package main

// Item 1/2 of the 1.0 readiness blocker pass: the front must append its own
// peer to X-Forwarded-For (and restore Proto/Host from the inbound request)
// instead of passing the header straight through - see main.go's newProxy
// comment for why. Without this every request reached Flask as if it came
// from the loopback address this process uses to talk to gunicorn.

import (
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
)

func newProxyFront(t *testing.T) (*httptest.Server, chan http.Header) {
	t.Helper()
	headers := make(chan http.Header, 1)
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		headers <- r.Header.Clone()
		w.WriteHeader(http.StatusOK)
	}))
	t.Cleanup(upstream.Close)

	upstreamURL, err := url.Parse(upstream.URL)
	if err != nil {
		t.Fatal(err)
	}
	proxy := newProxy(upstreamURL)
	front := httptest.NewServer(proxy)
	t.Cleanup(front.Close)
	return front, headers
}

func TestProxyAppendsPeerToExistingForwardedFor(t *testing.T) {
	front, headers := newProxyFront(t)

	req, _ := http.NewRequest("GET", front.URL+"/anything", nil)
	req.Header.Set("X-Forwarded-For", "203.0.113.9")
	req.Header.Set("X-Forwarded-Proto", "https")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	got := <-headers
	xff := got.Get("X-Forwarded-For")
	parts := strings.Split(xff, ", ")
	if len(parts) != 2 || parts[0] != "203.0.113.9" {
		t.Fatalf("X-Forwarded-For = %q, want \"203.0.113.9, <peer>\"", xff)
	}
	if parts[1] == "" {
		t.Fatalf("X-Forwarded-For = %q, missing the appended peer", xff)
	}
	// The test client itself is the peer as far as the proxy is concerned.
	if !strings.Contains(parts[1], "127.0.0.1") {
		t.Fatalf("appended peer = %q, want the loopback test client address", parts[1])
	}
	// SetXForwarded would otherwise stomp this to "http" because the
	// connection between the test client and the front is never TLS.
	if got.Get("X-Forwarded-Proto") != "https" {
		t.Fatalf("X-Forwarded-Proto = %q, want the inbound value preserved", got.Get("X-Forwarded-Proto"))
	}
}

func TestProxySetsOnlyThePeerWhenNoForwardedForHeaderArrives(t *testing.T) {
	front, headers := newProxyFront(t)

	req, _ := http.NewRequest("GET", front.URL+"/anything", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	got := <-headers
	xff := got.Get("X-Forwarded-For")
	if xff == "" || strings.Contains(xff, ",") {
		t.Fatalf("X-Forwarded-For = %q, want a single peer address with no chain", xff)
	}
	if !strings.Contains(xff, "127.0.0.1") {
		t.Fatalf("X-Forwarded-For = %q, want the loopback test client address", xff)
	}
}

// Fix round 1, item 7: the two cases the reviewer found missing coverage for.

func TestProxyRestoresInboundForwardedHost(t *testing.T) {
	front, headers := newProxyFront(t)

	req, _ := http.NewRequest("GET", front.URL+"/anything", nil)
	req.Header.Set("X-Forwarded-Host", "mycelium.example")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	got := <-headers
	// SetXForwarded would otherwise set this to pr.In.Host, the front's own
	// listen address as the test client dialed it, not the public hostname
	// the outer proxy terminated for.
	if got.Get("X-Forwarded-Host") != "mycelium.example" {
		t.Fatalf("X-Forwarded-Host = %q, want the inbound value preserved", got.Get("X-Forwarded-Host"))
	}
}

func TestProxySynthesizesProtoFromTheConnectionWhenAbsent(t *testing.T) {
	front, headers := newProxyFront(t)

	// No X-Forwarded-Proto on the inbound request at all: nothing for this
	// process to restore, so SetXForwarded's own synthesis (derived from
	// whether the connection reaching this process is TLS) must stand. The
	// test client talks to the front over plain HTTP, so that is "http".
	req, _ := http.NewRequest("GET", front.URL+"/anything", nil)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()

	got := <-headers
	if got.Get("X-Forwarded-Proto") != "http" {
		t.Fatalf("X-Forwarded-Proto = %q, want \"http\" synthesized from the connection", got.Get("X-Forwarded-Proto"))
	}
}
