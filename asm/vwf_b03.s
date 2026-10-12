; VWF, bank 3 part (region vwf.b03, b03:$DE63-$DFFF). docs/design.md.
; Hooks (bank 3, patched by tools/mod_vwf.py):
;   $CC62  bbs7 $91,$CC5F      -> jmp vwf_hook          putc dispatch (every byte printed)
;   $CA68  jmp $CC50           -> jmp vwf_cursor_putc   menu cursor draw: original path, no VWF
;   $CA8C  jmp $CC50           -> jmp vwf_cursor_putc   wait-cursor blink: original path, no VWF
;   $CABA  stz $92 / stz $93   -> jsr vwf_winreset/nop  window open, close, reset: VWF depth, bold and cell reset
; Codes: 04 VWF on, 05 VWF off, 09 bold on, 0A bold off (bold set in bank $61 at $6880/$6900), 15 n pen x.
;   $CD37  brk                 -> jmp vwf_exhaust/nop   original slot search found no free slot
;   $CFF8  ldy $8E/cpy #$76/bcs -> jsr vwf_relx/bcs/nop  window clear/scroll/close release: extension slots
;   $C406  jsr $C295           -> jsr vwf_wclose        window close: unspill before the BAT is restored
; Defines from the build: VWF_CODE_BANK, VWF_FONT_BANK. Bank $60 is entered through its word table at
; $4000 (vwf_far: X = 0 vwf_core, 2 vwf_reclaim, 4 vwf_finalize, 6 vwf_unspill).

.include "vwf_ram.inc"

.segment "CODE"

; ---- putc dispatch. Entered by jmp from $CC62 with A = byte (X, Y, A pushed by $CC53). ----
vwf_hook:
        bbs7 $91, @prefix       ; argument of a 10-1F code, or the kana after a DE/DF
        cmp #$20
        bcc @ctrl
        cmp #$80
        bcs @fixed              ; kana, kanji, DE/DF: original path
        ldx vwf_depth
        beq @fixed
        jmp vwf_glyph_far       ; 0x20-0x7F inside 04 ... 05
@fixed: ldx vwf_px              ; a fixed glyph starts on the next cell boundary
        beq @f1
        jsr vwf_snap
@f1:    jmp $CC65               ; original putc after its prefix test

@ctrl:  cmp #$04
        beq @on
        cmp #$05
        beq @off
        cmp #$09                ; bold on / off (no-ops in the original putc, $CB26)
        beq @bon
        cmp #$0A
        beq @boff
        cmp #$0C                ; cursor stop: record the next cell
        beq @snap
        cmp #$0B                ; waits: the ▼ goes in the next cell
        beq @snap
        cmp #$0E
        beq @snap
        cmp #$0D                ; newline sets the pen itself
        beq @rst
        cmp #$06                ; clears release slots: a recount may help again
        beq @clr
        cmp #$07
        beq @clr
        jmp $CAF4               ; original control dispatch (10-1F set the $91 prefix)
@snap:  jsr vwf_snap
        jmp $CAF4
@clr:   stz vwf_gcoff
@rst:   jsr vwf_reset
        jmp $CAF4
@on:    inc vwf_depth
        bne @r
        dec vwf_depth
@r:     rts
@off:   lda vwf_depth
        beq @boff
        dec vwf_depth
        bne @r
@boff:  stz vwf_bold            ; VWF text ended: regular weight again
        rts
@bon:   lda #1
        sta vwf_bold
        rts

@prefix:
        ldx $91
        cpx #$95                ; 15 n: pen x = n - 0x20 px on the current line
        beq @pen
        cpx #$91                ; 11 n / 12 n: column / row set
        beq @rp
        cpx #$92
        bne @cbd1
@rp:    jsr vwf_reset
@cbd1:  jmp $CBD1               ; original argument dispatch
@pen:   jsr vwf_fin
        stz $91
        sec
        sbc #$20
        tax
        and #$07
        sta vwf_px
        txa
        lsr a
        lsr a
        lsr a
        cmp $29D5
        bcc @p1
        cla                     ; outside the window: column 0
        stz vwf_px
@p1:    sta $7F
        stz vwf_open
        sta vwf_sx
        lda $80
        sta vwf_sy
        rts

; Finish the open cell: if the pen is inside a cell (px > 0) and nobody moved it, go to the next
; cell. Then no cell is open. Keeps A.
vwf_snap:
        pha
        lda vwf_px
        beq @r
        lda $7F
        cmp vwf_sx
        bne @r
        lda $80
        cmp vwf_sy
        bne @r
        jsr vwf_fin
        jsr $CE53
@r:     pla
vwf_reset:
        jsr vwf_fin
        stz vwf_px
        stz vwf_open
        rts

; Finish the open cell (vwf_finalize: share an identical cell or make it shareable). Keeps A X Y.
vwf_fin:
        pha
        lda vwf_open
        beq @r
        phx
        phy
        ldx #4
        jsr vwf_far
        ply
        plx
@r:     pla
        rts

; $CABA (window open via $CAA9, close via $CF92/$C412, cache reset $CAD9): the replaced
; stz $92 / stz $93, plus VWF off, no open cell, recount allowed again.
vwf_winreset:
        stz $92
        stz $93
        tst #$FF, vwf_keep      ; set by ui's PANELKEEP (b07 $C171): the shop/inn panel is re-selected
        bne @keep               ; between an item name and its fragment; $7F/$80 come back, keep the cell
        stz vwf_depth
        stz vwf_bold
        stz vwf_gcoff
        bra vwf_reset
@keep:  rts

; Map the VWF code (MPR2) and font (MPR3), draw A proportionally, restore both MPRs.
vwf_glyph_far:
        sta vwf_code
        clx
; Call bank $60 entry X (word table at $4000) with bank $60 at MPR2 and the font at MPR3. Clobbers A.
vwf_far:
        tma #$04
        pha
        tma #$08
        pha
        lda #VWF_CODE_BANK
        clc
        adc $2200               ; ROM bank base, as every banking routine of the game
        tam #$04
        lda #VWF_FONT_BANK
        clc
        adc $2200
        tam #$08
        jsr @go
        pla
        tam #$08
        pla
        tam #$04
        rts
@go:    jmp ($4000,x)

; $CA68 / $CA8C: menu cursor ▶ and wait cursor ▼ draws. The original putc ($CC50) minus the hook.
vwf_cursor_putc:
        stz $294A
        phy
        phx
        pha
        jsr @orig
        pla
        plx
        ply
        rts
@orig:  bbs7 $91, @arg
        jmp $CC65
@arg:   jmp $CBD1

; $CD37: the original slot search ($CD08) found no free slot (X = $76). It used to BRK (the game hung).
; Now: recount the references (vwf_gc) once and take a freed slot ($CD42 continues the original
; allocation with X = slot). Still none: set the error flag, leave the cell blank, advance one
; cell and return from putc.
vwf_exhaust:
        lda vwf_gcoff
        bne @fail
        ldx #2
        jsr vwf_far             ; vwf_reclaim (recount, spill), keeps $83/$84 (the glyph looked up)
        clx
@l:     lda $28D3,x
        and #$3F
        beq @ok
        inx
        cpx #$76
        bne @l
        lda #1
        sta vwf_gcoff
@fail:  lda #$02
        tsb vwf_err
        inc vwf_errcnt
        bne @e1
        dec vwf_errcnt
@e1:    pla                     ; A, X, Y saved by $CD08
        plx
        ply
        pla                     ; return address into the caller of $CD08 (putc body)
        pla
        jmp $CE53               ; its rts returns from putc
@ok:    jmp $CD42

; $CFF8 (in $CFD9, the release of one BAT text row on a window clear, scroll or close): A = high part
; of (tile - cache base) >> 1 (palette bits on top), $8E = slot. The original went on with
; ldy $8E / cpy #$76 / bcs skip. Extension tiles ($5B2-$5FF, field base $20A: A&7 = 1, $8E = $D4+k)
; drop one reference of extension slot k here and return C=1 (skip); everything else returns
; Y = $8E and the original carry. Keeps X (the loop index).
vwf_relx:
        ldy $8E
        and #$07
        cmp #$01
        bne @o
        cpy #$D4
        bcc @o
        cpy #$D4+EXT_N
        bcs @o
        sxy
        lda ext_ref-$D4,x
        beq @k
        dec ext_ref-$D4,x
@k:     sxy
        sec
        rts
@o:     cpy #$76
        rts

; $C406 (window close, $C3F9): the save-stack block of the closed window is about to be copied back
; to the BAT by $C295. If cells were spilled while this window was on top, give them slots and
; rewrite their markers first (vwf_unspill).
vwf_wclose:
        lda spill_n
        beq @j
        ldx #6
        jsr vwf_far
@j:     jmp $C295
