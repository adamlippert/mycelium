package main

// .fsh cache parsing and the virtual moov-first layout, mirroring
// mp4_faststart.load() and serve_bytes() byte for byte. The Python side
// builds these files; this side only reads them.
//
// File format:   [8B ftyp_size][8B moov_size][8B cdn_size][8B moov_offset][ftyp+moov bytes]
// Legacy format (files under 32 bytes, sentinel-sized): the first three
// fields only, header from byte 24.
//
// Virtual layout: [ftyp][moov_rewritten][mdat1][mdat2]
// CDN layout:     [ftyp][mdat1][moov][mdat2]
//
// Mapping for CDN regions:
//   mdat1: virtual [hdr_size, moov_offset+moov_size) -> cdn = virtual - moov_size
//   mdat2: virtual [moov_offset+moov_size, cdn_size) -> cdn = virtual (unchanged)

import (
	"encoding/binary"
	"fmt"
	"os"
)

type fshInfo struct {
	FtypSize   uint64
	MoovSize   uint64
	CdnSize    uint64
	MoovOffset uint64
	Header     []byte
}

func (f *fshInfo) headerSize() uint64 { return uint64(len(f.Header)) }
func (f *fshInfo) alreadyFast() bool  { return f.MoovSize == 0 }

func loadFsh(path string) (*fshInfo, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	if len(raw) < 24 {
		return nil, fmt.Errorf("fsh %s: truncated (%d bytes)", path, len(raw))
	}
	info := &fshInfo{
		FtypSize: binary.BigEndian.Uint64(raw[0:8]),
		MoovSize: binary.BigEndian.Uint64(raw[8:16]),
		CdnSize:  binary.BigEndian.Uint64(raw[16:24]),
	}
	if len(raw) < 32 {
		// Legacy three-field header (sentinel-sized files).
		if info.MoovSize == 0 {
			info.MoovOffset = info.FtypSize
		} else {
			info.MoovOffset = info.CdnSize - info.MoovSize
		}
		info.Header = raw[24:]
	} else {
		info.MoovOffset = binary.BigEndian.Uint64(raw[24:32])
		info.Header = raw[32:]
	}
	return info, nil
}

// region is one contiguous piece of a virtual-range read: either a slice of
// the cached header or a byte range fetched from the CDN.
type region struct {
	FromHeader bool
	HdrStart   uint64 // valid when FromHeader
	HdrEnd     uint64 // inclusive
	CdnStart   uint64 // valid when !FromHeader
	CdnEnd     uint64 // inclusive
}

// virtualRegions maps the inclusive virtual range [vStart, vEnd] onto cached
// header bytes and CDN ranges, in serving order. Mirrors serve_bytes().
func (f *fshInfo) virtualRegions(vStart, vEnd uint64) []region {
	var out []region
	hdrSize := f.headerSize()
	mdat2Start := f.MoovOffset + f.MoovSize
	pos := vStart

	// Region 1: cached header (ftyp + rewritten moov)
	if pos < hdrSize {
		chunkEnd := min(vEnd, hdrSize-1)
		out = append(out, region{FromHeader: true, HdrStart: pos, HdrEnd: chunkEnd})
		pos = chunkEnd + 1
	}

	// Region 2: mdat1 (before moov in CDN): cdn = virtual - moov_size
	if pos <= vEnd && pos < mdat2Start {
		chunkEnd := min(vEnd, mdat2Start-1)
		out = append(out, region{CdnStart: pos - f.MoovSize, CdnEnd: chunkEnd - f.MoovSize})
		pos = chunkEnd + 1
	}

	// Region 3: mdat2 (after moov in CDN): cdn = virtual
	if pos <= vEnd {
		out = append(out, region{CdnStart: pos, CdnEnd: vEnd})
	}
	return out
}
