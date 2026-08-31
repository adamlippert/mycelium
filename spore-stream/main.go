// spore-stream: the Go streaming front for Mycelium.
//
// Listens on the container's exposed port. It owns exactly one path family,
// /spore-stream/<token>, where each open stream costs a goroutine instead of
// one of gunicorn's OS threads; every other request is reverse-proxied to
// gunicorn unchanged. Python keeps every decision (materialize, the TorBox
// budget, liveness checks, .fsh cache builds) behind
// /internal/stream-resolve/<token>; this process only shovels bytes.
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

func main() {
	listen := env("STREAM_LISTEN", "0.0.0.0:8088")
	upstreamRaw := env("STREAM_UPSTREAM", "http://127.0.0.1:8090")
	upstream, err := url.Parse(upstreamRaw)
	if err != nil {
		log.Fatalf("spore-stream: bad STREAM_UPSTREAM %q: %v", upstreamRaw, err)
	}

	proxy := &httputil.ReverseProxy{
		Rewrite: func(pr *httputil.ProxyRequest) {
			pr.SetURL(upstream)
			pr.Out.Host = pr.In.Host
			// Pass X-Forwarded-* through untouched instead of appending this
			// hop, so Flask sees exactly the headers the outer proxy set and
			// its trusted-header auth and logging behave as before.
			pr.Out.Header["X-Forwarded-For"] = pr.In.Header["X-Forwarded-For"]
			pr.Out.Header["X-Forwarded-Proto"] = pr.In.Header["X-Forwarded-Proto"]
			pr.Out.Header["X-Forwarded-Host"] = pr.In.Header["X-Forwarded-Host"]
		},
		// Flush every write immediately: gunicorn streams some responses
		// (server-sent progress, chunked JSON) and buffering would stall them.
		FlushInterval: -1,
		ErrorHandler: func(w http.ResponseWriter, r *http.Request, err error) {
			log.Printf("proxy error %s %s: %v", r.Method, r.URL.Path, err)
			w.WriteHeader(http.StatusBadGateway)
		},
	}

	streamer := newStreamer(upstreamRaw)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		// The resolve endpoint (and anything else under /internal/) is
		// loopback-only business between this process and gunicorn.
		if strings.HasPrefix(r.URL.Path, "/internal/") {
			http.NotFound(w, r)
			return
		}
		if token, ok := strings.CutPrefix(r.URL.Path, "/spore-stream/"); ok && !strings.Contains(token, "/") && token != "" {
			streamer.serve(w, r, token)
			return
		}
		proxy.ServeHTTP(w, r)
	})

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
