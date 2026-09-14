// spore-stream: the Go streaming front for Mycelium.
//
// Listens on the container's exposed port. It owns exactly one path family,
// /spore-stream/<token>, where each open stream costs a goroutine instead of
// one of gunicorn's OS threads; every other request is reverse-proxied to
// gunicorn unchanged, except for the two loopback-only path families
// (/internal/ and /spore-nfs/), which are refused with a 404. Python keeps
// every decision (materialize, the TorBox budget, liveness checks, .fsh
// cache builds) behind /internal/stream-resolve/<token>; this process only
// shovels bytes.
//
// Disable with STREAM_FRONT_ENABLED=false (see the Dockerfile CMD): gunicorn
// then binds the exposed port directly and its own /spore-stream route,
// which remains a complete implementation, serves the streams.
package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"
)

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// newProxy builds the reverse proxy to gunicorn. Extracted from main so the
// X-Forwarded-* rewriting can be exercised directly in tests.
func newProxy(upstream *url.URL) *httputil.ReverseProxy {
	return &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(upstream)
			pr.Out.Host = pr.In.Host
			// Copy the inbound X-Forwarded-For first so SetXForwarded (below)
			// appends this hop's peer to it instead of replacing it - Flask
			// needs the whole chain to tell the real client from the proxies
			// in front of it. Without this step every request reached Flask
			// as if it came from 127.0.0.1 (this process's own loopback
			// connection to gunicorn), which made the trusted-proxy header
			// check and the login rate limiter both key on the same address
			// for every caller.
			pr.Out.Header["X-Forwarded-For"] = pr.In.Header["X-Forwarded-For"]
			// Appends the peer that connected to this process (the outer
			// proxy, or the client directly) and sets X-Forwarded-Host/Proto
			// from the inbound connection.
			pr.SetXForwarded()
			// SetXForwarded derives Proto from whether *this* connection is
			// TLS, which it never is - TLS terminates upstream at the outer
			// proxy - so it would set "http" even for an HTTPS visitor.
			// Restore the values the inbound request actually carried,
			// keeping the outer proxy as the source of truth when present.
			if v := pr.In.Header.Get("X-Forwarded-Proto"); v != "" {
				pr.Out.Header.Set("X-Forwarded-Proto", v)
			}
			if v := pr.In.Header.Get("X-Forwarded-Host"); v != "" {
				pr.Out.Header.Set("X-Forwarded-Host", v)
			}
			// Overwrites any client-sent value: requests through the front
			// carry it, so Flask can report "front active" as live truth.
			pr.Out.Header.Set("X-Stream-Front", "1")
		},
		// Flush every write immediately: gunicorn streams some responses
		// (server-sent progress, chunked JSON) and buffering would stall them.
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("proxy error %s %s: %v", r.Method, r.URL.Path, err)
			w.WriteHeader(http.StatusBadGateway)
		},
	}
}

// newRouter builds the front's one handler: /spore-stream/<token> is served
// here, /internal/ and /spore-nfs/ are refused, everything else goes to
// gunicorn. Extracted from main so the routing decisions can be exercised
// directly in tests without a real streamer.
func newRouter(proxy http.Handler, serveStream func(http.ResponseWriter, *http.Request, string)) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// The resolve endpoint (and anything else under /internal/) is
		// loopback-only business between this process and gunicorn.
		// /spore-nfs/ is the same kind of traffic: the tree and size
		// endpoints exist for the NFS and SMB helpers running beside
		// gunicorn in this container, and the tree lists every playable
		// token, which is an unauthenticated capability link. Both
		// families answer 404 rather than 403, so an outside caller
		// learns nothing about what does exist here. Python refuses
		// them over the same rule; this is the outer line.
		if strings.HasPrefix(r.URL.Path, "/internal/") || strings.HasPrefix(r.URL.Path, "/spore-nfs/") {
			http.NotFound(w, r)
			return
		}
		if token, ok := strings.CutPrefix(r.URL.Path, "/spore-stream/"); ok && !strings.Contains(token, "/") && token != "" {
			serveStream(w, r, token)
			return
		}
		proxy.ServeHTTP(w, r)
	})
	return mux
}

func main() {
	listen := env("STREAM_LISTEN", "0.0.0.0:8088")
	upstreamRaw := env("STREAM_UPSTREAM", "http://127.0.0.1:8090")
	upstream, err := url.Parse(upstreamRaw)
	if err != nil {
		log.Fatalf("spore-stream: bad STREAM_UPSTREAM %q: %v", upstreamRaw, err)
	}

	proxy := newProxy(upstream)

	streamer := newStreamer(upstreamRaw)

	mux := newRouter(proxy, streamer.serve)

	srv := &http.Server{
		Addr:              listen,
		Handler:           mux,
		ReadHeaderTimeout: 15 * time.Second,
		IdleTimeout:       120 * time.Second,
		// No ReadTimeout/WriteTimeout: streams legitimately stay open for
		// the length of a movie.
	}
	log.Printf("spore-stream: listening on %s, upstream %s", listen, upstreamRaw)
	log.Fatal(srv.ListenAndServe())
}
