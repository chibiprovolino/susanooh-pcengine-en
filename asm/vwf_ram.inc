; VWF state in work RAM (docs/design.md: $2604-$263F belongs to the vwf module).
; Shared by asm/vwf_b03.s (bank 3 hook) and asm/vwf_far.s (core in bank $60).
; Equates are not exported to the build's label table; only code labels are.

vwf_depth   = $2604     ; 04/05 nesting depth (glyphs 0x20-0x7F draw proportionally while > 0)
vwf_px      = $2605     ; pen offset in px inside cell ($7F,$80): 0-7, or 8 = cell full (advance lazily)
vwf_open    = $2606     ; 1 = cell ($7F,$80) has a slot of its own and vwf_cur holds its pixels
vwf_tlo     = $2607     ; tile number of the open cell (top tile; bottom = +1)
vwf_thi     = $2608
vwf_sx      = $2609     ; $7F/$80 when the state above was last valid (anything else = moved externally)
vwf_sy      = $260A
vwf_err     = $260B     ; bit0: a VWF cell found no free slot (skipped); bit1: original putc found none ($CD37)
vwf_errcnt  = $260C     ; number of failed slot allocations (saturates at 255)
vwf_code    = $260D     ; glyph code being drawn
vwf_wid     = $260E     ; its advance
vwf_ink     = $260F     ; non-zero if the glyph has pixels in the current cell
vwf_ink2    = $2610     ; non-zero if it has pixels in the next cell
vwf_tmp     = $2611
vwf_used    = $2612     ; slots in use at the last recount or failed VWF allocation (statistics for tests)
vwf_peak    = $2613     ; unused (reserved)
vwf_cur     = $2614     ; 16 rows of the open cell ($2614-$2623)
vwf_nxt     = $2624     ; 16 rows spilling into the next cell ($2624-$2633)
vwf_gcoff   = $2634     ; 1 = a recount found no free slot: none again until a window opens/closes/clears
vwf_gccnt   = $2635     ; recounts run (saturates at 255; statistics for tests)
vwf_gcfree  = $2636     ; free slots right after the last recount
vwf_relcnt  = $2637     ; slots released because a new VWF cell replaced them (wraps; statistics)
vwf_bold    = $2638     ; 1 = bold set (codes 09 on / 0A off; cleared by 05 to depth 0 and by window open/close)
vwf_slot    = $2639     ; slot of the open cell: 0-$75 main cache, $80+k extension slot k
vwf_hash    = $263A     ; finalize: code byte ($C0-$FE) of the cell being finished
vwf_s7f     = $263B     ; finalize: saved $7F, $80, $90, $1A (pen, palette, VDC increment shadow)
vwf_s80     = $263C
vwf_s90     = $263D
vwf_s1a     = $263E
vwf_tmp2    = $263F

; Extension slots (VWF cells only, field mode = cache base $20A): VRAM tiles $5B2-$5FF, 39 cells.
; Nothing of the game uses them in field mode (sprites end at $597, portrait $598-$5B0).
EXT_N       = 39
EXT_TILE    = $05B2     ; top tile of extension slot 0 (slot k: $5B2 + 2k)
ext_ref     = $2660     ; 39 reference counts ($2660-$2686), 0 = free (bit7: seen as a bottom tile, only inside vwf_gc)
ext_code    = $2687     ; 39 code bytes ($2687-$26AD): $FF open / not shareable, $C0-$FE content hash
vwf_dedup   = $26B8     ; finished cells that were shared with an identical cell (wraps; statistics)
vwf_extused = $26B9     ; extension slots in use after the last allocation (statistics)
vwf_extpk   = $26BA     ; peak of vwf_extused (statistics)
vwf_extok   = $26BB     ; GC: 1 = cache base is $20A (extension slots valid)
vwf_tmp3    = $26BC
vwf_keep    = $26BD     ; non-zero: vwf_winreset leaves the pen/cell state alone (set around b07 $C081 by ui PANELKEEP)

; Spill (vwf_spill / vwf_unspill in vwf_far.s): one group of up to SPILL_MAX records of 8 words, made
; while window spill_dp was the top window, stored in VRAM at spill_lo/hi (save stack top at that time).
spill_n     = $26AE     ; records in the group (0 = none)
spill_dp    = $26AF     ; $2276 when the group was made
spill_lo    = $26B2     ; VRAM address of record 0
spill_hi    = $26B3
vwf_vec     = $26B4     ; 2 bytes: mapper called by vwf_walk
spill_i     = $26B6     ; unspill: record index
spill_cnt   = $26B7     ; unspill: records in the group; spill: records made by this call

; Scratch used only inside vwf_gc, vwf_spill and vwf_unspill (the game rebuilds it before every use:
; $CEF0/$CE9C fill it per call)
vwf_bmark   = $3200     ; 118 bytes: slot seen as a bottom tile during a recount
