; VWF core (docs/design.md). Bank $60, mapped at MPR2 ($4000) by
; vwf_glyph_far in bank 3; the font (bank $61) is mapped at MPR3 ($6000):
;   $6000 + code      advance in px (0 = no glyph)
;   $6080 + code*16   16 rows, MSB = leftmost pixel, row 0 = top of the 8x16 cell
;   $6880 + code / $6900 + code*16: the bold set, used while vwf_bold is set (advance up to 9)
; Bank 3 (putc's own bank) stays mapped at MPR6, so the original routines are called directly:
;   $CE53 next cell (wraps/scrolls)  $CE5F newline  $CEC7 per-character delay
;   $CE46 slot -> $86, tile $81/$82  $D020 BAT entry for ($7F,$80)  $E2D5 (bank 0) VRAM increment 1
;   $FB7D $FB98 $FBB3 $C8C2 $FBC5: the BAT address helpers $D020 uses
; Zero page $8A-$8F is putc scratch (the original glyph path and $CFD9 use it the same way).
; Bank 3 enters through the word table at $4000: jmp ($4000,x), X = 0 core, 2 reclaim (recount, then
; spill), 4 finalize, 6 unspill.

.include "vwf_ram.inc"

.segment "CODE"

        .word vwf_core, vwf_reclaim, vwf_finalize, vwf_unspill


; Draw glyph vwf_code (0x20-0x7F) proportionally at the pen. Called once per glyph.
vwf_core:
        lda vwf_px              ; state left by the previous glyph still valid?
        ora vwf_open
        beq @fresh
        lda $7F
        cmp vwf_sx
        bne @stale
        lda $80
        cmp vwf_sy
        beq @fresh
@stale: jsr vwf_finalize        ; the pen was moved by other code: the open cell is finished,
        stz vwf_px              ; start a new cell there
        stz vwf_open
@fresh: lda vwf_px
        cmp #8
        bcc @width
        jsr vwf_finalize
        jsr $CE53               ; previous glyph filled the cell exactly: advance now
        stz vwf_px
        stz vwf_open
@width: ldx vwf_code
        lda vwf_bold
        bne @bw
        lda $6000,x
        bra @w0
@bw:    lda $6880,x             ; bold advance
@w0:    bne @w1
        rts                     ; undefined code: nothing drawn, pen unchanged
@w1:    sta vwf_wid
        lda $7F                 ; safety net: the line (cells $29D5 * 8 px) is full -> newline
        asl a
        asl a
        asl a
        clc
        adc vwf_px
        clc
        adc vwf_wid
        sta vwf_tmp
        lda $29D5
        asl a
        asl a
        asl a
        cmp vwf_tmp
        bcs @fits
        jsr vwf_finalize
        jsr $CE5F
        stz vwf_px
        stz vwf_open
@fits:  lda $7F                 ; the cell being drawn (vwf_finalize uses vwf_sx/sy)
        sta vwf_sx
        lda $80
        sta vwf_sy
        jsr $CEC7               ; message speed: one character delay per glyph

        stz $8B                 ; ($8A) = $6080 + code*16 (bold: $6900 + code*16)
        lda vwf_code
        asl a
        rol $8B
        asl a
        rol $8B
        asl a
        rol $8B
        asl a
        rol $8B
        ldy vwf_bold
        bne @bg
        clc
        adc #$80
        sta $8A
        lda $8B
        adc #$60
        sta $8B
        bra @gp
@bg:    sta $8A
        lda $8B
        clc
        adc #$69
        sta $8B
@gp:

        lda vwf_open            ; a new cell starts empty
        bne @shift
        ldx #15
@clr:   stz vwf_cur,x
        dex
        bpl @clr
@shift: stz vwf_ink
        stz vwf_ink2
        cly
@row:   lda ($8A),y             ; cur |= g >> px ; nxt = g << (8 - px)
        stz $8C
        ldx vwf_px
        beq @ns
@sh:    lsr a
        ror $8C
        dex
        bne @sh
@ns:    tax
        ora vwf_ink
        sta vwf_ink
        txa
        ora vwf_cur,y
        sta vwf_cur,y
        lda $8C
        sta vwf_nxt,y
        ora vwf_ink2
        sta vwf_ink2
        iny
        cpy #16
        bne @row

        lda vwf_ink             ; pixels in this cell: upload (new cell: slot + BAT first)
        beq @adv
        lda vwf_open
        bne @upd
        jsr vwf_alloc
        bcs @adv                ; no free slot: skipped, error flag set
        jsr vwf_upload
        jsr vwf_bat
        bra @adv
@upd:   jsr vwf_upload

@adv:   lda vwf_px
        clc
        adc vwf_wid
        sta vwf_px
        cmp #9
        bcc @done               ; still inside the cell (8 = full, advanced by the next glyph)
        sbc #8                  ; carry is set
        sta vwf_px
        jsr vwf_finalize        ; the cell is complete
        jsr $CE53               ; the glyph crosses into the next cell
        stz vwf_open
        ldx #15
@cp:    lda vwf_nxt,x
        sta vwf_cur,x
        dex
        bpl @cp
        lda vwf_ink2
        beq @done
        jsr vwf_alloc
        bcs @done
        jsr vwf_upload
        jsr vwf_bat
@done:  lda $7F
        sta vwf_sx
        lda $80
        sta vwf_sy
        rts

; Take a glyph-cache slot for the cell at the pen. First the slot the cell shows now (if any) loses
; this cell's reference, as a window clear would do. Pools: the 118 main slots (shared with the
; original glyph cache) and, in field mode (cache base $20A), 39 extension slots at VRAM tiles
; $5B2-$5FF that only VWF cells use. A new cell takes a main slot while more than RESERVE main slots
; are free (the rest stays for the original fixed glyphs: digits, uppercase labels, kana), then an
; extension slot, then (one recount, vwf_gc) again main above the reserve or extension, and last
; the main reserve (with a spill of hidden cells, vwf_spill, before that). A main slot is marked code $FF / type $C0 (no lookup of the original path can
; match it: kanji indexes stop at $BF) with refcount 1, so the window clear, scroll and close
; ($CFD9, extension slots through the b03 $CFF8 hook) release it like any other slot. Nothing
; free: C=1, error flag, the cell is skipped. C=0 ok: vwf_open=1, vwf_slot, vwf_tlo/thi = top tile.
RESERVE = 12

vwf_alloc:
        jsr vwf_release_cell
vwf_take:                       ; (entry without the release: vwf_unspill)
        jsr vwf_mainfree        ; Y = free main slots, X = first free
        cpy #RESERVE+1
        bcs @main
        jsr vwf_extfree
        bcc @ext
        lda vwf_gcoff
        bne @last
        jsr vwf_gc
        jsr vwf_mainfree
        cpy #RESERVE+1
        bcs @main
        jsr vwf_extfree
        bcc @ext
        jsr vwf_spill           ; cells kept only for the windows under the top one give their slots up
        bcs @nosp
        jsr vwf_mainfree
        cpy #RESERVE+1
        bcs @main
@nosp:  lda #1                  ; did not help: no more recounts until a window opens/closes/clears
        sta vwf_gcoff
@last:  jsr vwf_mainfree
        cpy #0
        bne @main
        lda #$76                ; statistics: slots in use when it failed
        sta vwf_used
        lda #$01
        tsb vwf_err
        inc vwf_errcnt
        bne @f
        dec vwf_errcnt
@f:     sec
        rts
@main:  lda #$FF
        sta $285D,x
        lda #$C1
        sta $28D3,x
        stx vwf_slot
        txa                     ; tile = base + slot*2
        asl a
        clc
        adc $96
        sta vwf_tlo
        cla
        adc $97
        sta vwf_thi
        bra @ok
@ext:   lda #1
        sta ext_ref,x
        lda #$FF
        sta ext_code,x
        txa
        asl a
        clc
        adc #<EXT_TILE
        sta vwf_tlo
        lda #>EXT_TILE
        sta vwf_thi
        txa
        ora #$80
        sta vwf_slot
        jsr vwf_extcount
@ok:    lda #1
        sta vwf_open
        clc
        rts

; Y = number of free main slots, X = the first one (when Y > 0).
vwf_mainfree:
        cly
        ldx #$75
@l:     lda $28D3,x
        and #$3F
        bne @n
        iny
        stx vwf_tmp
@n:     dex
        bpl @l
        ldx vwf_tmp
        rts

; Extension slots exist only with the field cache base ($96/$97 = $020A). C=0: X = a free one.
vwf_extok_chk:                  ; Z=1 when the extension slots are usable
        lda $97
        cmp #$02
        bne @r
        lda $96
        cmp #$0A
@r:     rts

vwf_extfree:
        jsr vwf_extok_chk
        bne @no
        clx
@l:     lda ext_ref,x
        beq @y
        inx
        cpx #EXT_N
        bne @l
@no:    sec
        rts
@y:     clc
        rts

; Statistics: vwf_extused = extension slots in use, vwf_extpk = its peak. Keeps X.
vwf_extcount:
        phx
        cly
        clx
@l:     lda ext_ref,x
        beq @n
        iny
@n:     inx
        cpx #EXT_N
        bne @l
        sty vwf_extused
        cpy vwf_extpk
        bcc @r
        sty vwf_extpk
@r:     plx
        rts

; Y = number of main slots with refcount > 0.
vwf_count:
        cly
        clx
@c:     lda $28D3,x
        and #$3F
        beq @c1
        iny
@c1:    inx
        cpx #$76
        bne @c
        rts

; A = BAT entry low byte, Y = high byte. C=0: X = the slot whose TOP tile the entry shows (main
; 0-$75, extension $80+k). C=1: anything else (bottom tile, frame, map, pinned area...).
vwf_class:
        pha
        tya
        and #$07
        cmp #>EXT_TILE
        bne @main
        jsr vwf_extok_chk
        bne @main
        pla
        sec
        sbc #<EXT_TILE
        bcc @no
        lsr a
        bcs @no
        cmp #EXT_N
        bcs @no
        ora #$80
        tax
        clc
        rts
@main:  pla
        sec
        sbc $96
        sta vwf_tmp3
        tya
        and #$0F
        sbc $97
        bne @no
        lda vwf_tmp3
        lsr a
        bcs @no
        cmp #$76
        bcs @no
        tax
        clc
        rts
@no:    sec
        rts

; $285B/$285C = VRAM address of the BAT entry (top tile) of the cell ($7F,$80) in the current
; window, computed exactly as $D020 computes it ($D020-$D059).
vwf_cell_addr:
        lda $7F
        inc a
        lsr a
        clc
        adc $2277
        clc
        adc $2261
        sta $2854
        jsr $FB7D
        lda $80
        clc
        adc $2278
        clc
        adc $2263
        sta $2856
        jsr $FB98
        jsr $FBB3
        jsr $C8C2
        lda $7F
        and #$01
        eor #$01
        clc
        adc $285B
        adc #$40
        sta $285B
        jmp $FBC5

; A = low byte, Y = high byte of the VRAM word at $285B/$285C (VRAM increment set to 1).
vwf_read_word:
        jsr $E2D5
        lda #$01                ; MARR
        sta $18
        st0 #$01
        lda $285B
        sta a:$0002
        lda $285C
        sta a:$0003
        lda #$02                ; VRR
        sta $18
        st0 #$02
        lda a:$0002
        ldy a:$0003
        rts

; The cell at ($7F,$80) is about to get a new slot: drop one reference from the cache slot its BAT
; entry shows, as $CFD9 does on a clear. Pinned ($3F) and free slots, frame/blank tiles and anything
; outside the cache are left alone.
vwf_release_cell:
        jsr vwf_cell_addr
        jsr vwf_read_word
        jsr vwf_class
        bcs @r
        jsr vwf_unref
        bcc @r
        inc vwf_relcnt
@r:     rts

; Drop one reference of slot X (main or $80+k). C=1 if a reference was dropped.
vwf_unref:
        cpx #$80
        bcs @e
        lda $28D3,x
        and #$3F
        beq @no
        cmp #$3F
        beq @no
        dec $28D3,x
        sec
        rts
@e:     txa
        and #$7F
        tax
        lda ext_ref,x
        beq @no
        dec ext_ref,x
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------------------------
; Finish the open cell (vwf_open, at vwf_sx/vwf_sy, pixels in vwf_cur): if another finished VWF
; cell has exactly the same 16 rows, point this cell's BAT entries at that slot (one reference
; more) and free this cell's own slot; otherwise give the slot the content hash as its code byte
; ($C0-$FE) so later cells can share it. An open cell keeps code $FF and is never shared, so a cell
; still being drawn is never changed under another one. Nothing happens if the cell no longer
; shows this slot (window closed or cleared, slot released). Always clears vwf_open.
; Keeps $7F/$80/$90 and the VDC increment; clobbers A X Y, $81/$82, $8C-$8F, $2854-$285C.
vwf_finalize:
        lda vwf_open
        bne @go
        rts
@go:    stz vwf_open
        lda $7F
        sta vwf_s7f
        lda $80
        sta vwf_s80
        lda $90
        sta vwf_s90
        lda $1A
        sta vwf_s1a
        lda vwf_sx
        sta $7F
        lda vwf_sy
        sta $80
        jsr vwf_cell_addr
        jsr vwf_read_word
        cmp vwf_tlo             ; the cell still shows the open slot?
        beq @t1
@outj:  jmp @out
@t1:    tya
        and #$07
        cmp vwf_thi
        bne @outj
        tya
        and #$F0
        sta $90                 ; its palette, for the BAT rewrite
        ldx vwf_slot            ; the slot is still the open one (refcount 1+, code $FF)?
        cpx #$80
        bcs @x1
        lda $285D,x
        cmp #$FF
        bne @outj
        lda $28D3,x
        and #$3F
        beq @outj
        bra @hash
@x1:    txa
        and #$7F
        tax
        lda ext_code,x
        cmp #$FF
        bne @outj
        lda ext_ref,x
        beq @outj
@hash:  jsr vwf_hashcur
        ldx #$75                ; main slots with the same code byte (type $C0, refcount 1-$3C)
@m:     cpx vwf_slot
        beq @mn
        lda $285D,x
        cmp vwf_hash
        bne @mn
        lda $28D3,x
        cmp #$C1
        bcc @mn
        cmp #$FD
        bcs @mn
        txa
        asl a
        clc
        adc $96
        sta $81
        cla
        adc $97
        sta $82
        phx
        jsr vwf_cmpcell
        plx
        bcs @mn
        inc $28D3,x
        bra @share
@mn:    dex
        bpl @m
        jsr vwf_extok_chk       ; extension slots
        bne @keep
        ldx #EXT_N-1
@e:     txa
        ora #$80
        cmp vwf_slot
        beq @en
        lda ext_code,x
        cmp vwf_hash
        bne @en
        lda ext_ref,x
        beq @en
        cmp #$3D
        bcs @en
        txa
        asl a
        clc
        adc #<EXT_TILE
        sta $81
        lda #>EXT_TILE
        sta $82
        phx
        jsr vwf_cmpcell
        plx
        bcs @en
        inc ext_ref,x
        bra @share
@en:    dex
        bpl @e
@keep:  ldx vwf_slot            ; no twin: this cell becomes shareable
        lda vwf_hash
        cpx #$80
        bcs @k1
        sta $285D,x
        bra @out
@k1:    pha
        txa
        and #$7F
        tax
        pla
        sta ext_code,x
        bra @out
@share: jsr $D020               ; BAT top/bottom of ($7F,$80) -> the twin's tiles ($81/$82), palette $90
        ldx vwf_slot
        jsr vwf_unref           ; our own slot: refcount 1 -> 0, free
        ldx vwf_slot
        cpx #$80
        bcc @s1
        jsr vwf_extcount
@s1:    inc vwf_dedup
@out:   lda vwf_s7f
        sta $7F
        lda vwf_s80
        sta $80
        lda vwf_s90
        sta $90
        lda vwf_s1a             ; VDC increment as the caller had it (64 after $D020, else 1)
        and #$18
        beq @i1
        jmp $E2EC
@i1:    jmp $E2D5

; vwf_hash = $C0 + a 6-bit hash of vwf_cur ($C0-$FE; $FF stays "open").
vwf_hashcur:
        cla
        ldx #15
@h:     asl a
        adc #0
        eor vwf_cur,x
        dex
        bpl @h
        sta vwf_tmp
        lsr a
        lsr a
        eor vwf_tmp
        and #$3F
        cmp #$3F
        bne @h1
        lda #$3E
@h1:    ora #$C0
        sta vwf_hash
        rts

; Compare the cell whose top tile is $81/$82 with vwf_cur: rows 0-7 = low bytes of words 0-7 of
; the top tile, rows 8-15 = words 0-7 of the bottom tile (words 8-15 hold planes 2/3, the same data).
; C=0 equal, C=1 different.
vwf_cmpcell:
        jsr $E2D5
        lda $82
        sta $8D
        lda $81
        asl a
        rol $8D
        asl a
        rol $8D
        asl a
        rol $8D
        asl a
        rol $8D
        sta $8C
        lda #$01                ; MARR = tile * 16
        sta $18
        st0 #$01
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        clx
@r:     cpx #8
        bcc @c
        cpx #16
        bcs @c
        lda a:$0002             ; words 8-15 (planes 2/3): skip
        lda a:$0003
        bra @n
@c:     txa
        cmp #16
        bcc @c1
        sbc #8                  ; words 16-23 -> rows 8-15
@c1:    tay
        lda a:$0002
        cmp vwf_cur,y
        bne @ne
        lda a:$0003
@n:     inx
        cpx #24
        bne @r
        clc
        rts
@ne:    sec
        rts

; ---------------------------------------------------------------------------------------------
; Recount the references of every slot that is not pinned, from the BAT ($0000-$0FFF, 64x64) and
; the window save stack (VRAM $7100 up to $75/$76, the BAT under the open windows; spill records
; are not BAT words and are skipped). Slots that
; nothing shows become free (refcounts the game leaked by drawing over cells come back).
; A slot counts once per top tile; a slot seen only as a bottom tile keeps 1. Pinned slots ($3F)
; stay. Extension slots are recounted the same way (field mode only). Runs only when the pools
; are short (about 2 frames). Clobbers A X Y, $8B-$8F, vwf_bmark.
vwf_gc:
        inc vwf_gccnt
        bne @g0
        dec vwf_gccnt
@g0:    ldx #$75
@z:     stz vwf_bmark,x
        lda $28D3,x
        and #$3F
        cmp #$3F
        beq @zn
        lda $28D3,x
        and #$C0
        sta $28D3,x
@zn:    dex
        bpl @z
        stz vwf_extok
        jsr vwf_extok_chk
        bne @g1
        inc vwf_extok
        ldx #EXT_N-1
@zx:    stz ext_ref,x
        dex
        bpl @zx
@g1:    jsr $E2D5
        stz $8C                 ; BAT: 4096 words from $0000
        stz $8D
        stz $8E
        lda #$10
        sta $8F
        jsr @scan
        stz $8C                 ; save stack: $7100 .. $75/$76, without the spill records
        lda #$71
        sta $8D
        lda $75
        ldy $76
        ldx spill_n
        beq @s1
        lda spill_lo
        ldy spill_hi
@s1:    jsr @rng
        lda spill_n
        beq @fin
        jsr vwf_spill_end
        sta $8C
        sty $8D
        lda $75
        ldy $76
        jsr @rng
@fin:   ldx #$75                ; seen only as a bottom tile: keep it
@b:     lda vwf_bmark,x
        beq @bn
        lda $28D3,x
        and #$3F
        bne @bn
        inc $28D3,x
@bn:    dex
        bpl @b
        lda vwf_extok
        beq @st
        ldx #EXT_N-1            ; extension: bit7 = seen as a bottom tile
@bx:    lda ext_ref,x
        bpl @bxn
        and #$7F
        bne @bx1
        lda #1
@bx1:   sta ext_ref,x
@bxn:   dex
        bpl @bx
        jsr vwf_extcount
@st:    clx                     ; statistics: free main slots now
        cly
@cf:    lda $28D3,x
        and #$3F
        bne @cf1
        iny
@cf1:   inx
        cpx #$76
        bne @cf
        sty vwf_gcfree
        tya                     ; and in use
        eor #$FF
        sec
        adc #$76
        sta vwf_used
        rts

; Count the words from $8C/$8D up to A/Y (at most up to $75/$76; nothing if that is not above).
@rng:   cpy $76
        bcc @r1
        bne @r0
        cmp $75
        bcc @r1
@r0:    lda $75
        ldy $76
@r1:    sec
        sbc $8C
        sta $8E
        tya
        sbc $8D
        sta $8F
        bcc @rx
        ora $8E
        beq @rx
        jmp @scan
@rx:    rts

; Read $8E/$8F words from VRAM $8C/$8D and count the cache references.
@scan:  lda #$01
        sta $18
        st0 #$01
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
@w:     lda a:$0002
        sta $8B
        sec
        sbc $96
        tax
        lda a:$0003
        and #$0F
        tay
        sbc $97
        bne @xt
        txa
        lsr a
        bcs @bot
        cmp #$76
        bcs @nx
        tax
        lda $28D3,x
        and #$3F
        cmp #$3E
        bcs @nx                 ; pinned, or saturated at 62
        inc $28D3,x
        bra @nx
@bot:   cmp #$76
        bcs @nx
        tax
        lda #1
        sta vwf_bmark,x
        bra @nx
@xt:    lda vwf_extok           ; extension tile? (high byte $05, low $B2-$FF)
        beq @nx
        cpy #>EXT_TILE
        bne @nx
        lda $8B
        sec
        sbc #<EXT_TILE
        bcc @nx
        lsr a
        tax
        bcs @xb
        lda ext_ref,x
        and #$7F
        cmp #$3E
        bcs @nx
        inc ext_ref,x
        bra @nx
@xb:    lda ext_ref,x
        ora #$80
        sta ext_ref,x
@nx:    lda $8E
        bne @d
        dec $8F
@d:     dec $8E
        lda $8E
        ora $8F
        bne @w
        rts

; Write vwf_cur (16 rows) to the open cell's two tiles. Every row byte b becomes the word (b,b)
; for planes 0/1 and again for planes 2/3, so ink is colour 15 in BAT palette $90, as the original.
vwf_upload:
        jsr $E2D5               ; VRAM auto-increment 1 ($D020 leaves it at 64)
        lda vwf_thi
        sta $8D
        lda vwf_tlo
        asl a
        rol $8D
        asl a
        rol $8D
        asl a
        rol $8D
        asl a
        rol $8D
        sta $8C
        lda #$00                ; MAWR = tile * 16
        sta $18
        st0 #$00
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02                ; VWR
        sta $18
        st0 #$02
        clx
        jsr @rows8              ; top tile, planes 0/1
        clx
        jsr @rows8              ; top tile, planes 2/3
        ldx #8
        jsr @rows8              ; bottom tile, planes 0/1
        ldx #8                  ; bottom tile, planes 2/3
@rows8: ldy #8
@r:     lda vwf_cur,x
        sta a:$0002
        sta a:$0003
        inx
        dey
        bne @r
        rts

; BAT entry of the cell at ($7F,$80) -> the open cell's tiles (palette $90).
vwf_bat:
        lda vwf_tlo
        sta $81
        lda vwf_thi
        sta $82
        jmp $D020

; ---------------------------------------------------------------------------------------------
; Entry 2 (b03 vwf_exhaust, the original glyph path found no free slot): recount, and if that frees
; no main slot, spill the hidden cells.
vwf_reclaim:
        jsr vwf_gc
        jsr vwf_mainfree
        cpy #0
        bne @r
        jmp vwf_spill
@r:     rts

; ---------------------------------------------------------------------------------------------
; Spill. Lists with many long names (status page 2 with every item over the battle windows, all
; teleport places) need more cells than the cache has, while the windows under the top one keep
; their cells only for the moment they are uncovered again. When the pools are exhausted, every
; finished VWF cell (code $C0-$FE) that the BAT does not show (it is referenced only from the window
; save stack) is copied to a record of 8 words (rows 2k / 2k+1 in the low / high byte) appended at
; the save stack top ($75/$76, which then moves past the records, so windows opened later save above
; them), and every save-stack word that shows it is replaced by a marker tile, $780 + 2i (top) /
; $781 + 2i (bottom) with its palette kept. Its slot is free then. Nothing of the game uses tiles
; $600-$7FF in a BAT entry or in the save stack (checked in 208 states), and the markers never reach
; the BAT: when the top window closes, vwf_unspill (b03 $C406, before the BAT under it is restored)
; gives every record that is still marked a slot again and rewrites its markers. One group of records
; at a time, made while window spill_dp (= $2276) is the top window; records stay below $7C00 (VRAM
; $7500-$7BFF is unused above the save stack in all 208 states; the save stack top never passed $74C0).
; C=0: slots were freed. Clobbers A X Y, $8B-$8F, vwf_bmark.
MARK_HI = $07                   ; markers: tiles $780-$7FF
SPILL_MAX = 64

vwf_spill:
        lda $2276
        beq @no
        lda $76
        cmp #$71
        bcc @no                 ; nothing saved
        cmp #$7A
        bcs @no                 ; no room for 64 records below $7C00
        lda spill_n
        beq @new
        lda $2276
        cmp spill_dp
        bcc @new                ; that group is stale (its window is gone without a close): drop it
        bne @no                 ; a window above the group's window: no second group
        jsr vwf_spill_end       ; the same top window: the records must still end at the stack top
        cmp $75
        bne @no
        cpy $76
        beq @go
@no:    sec
        rts
@new:   stz spill_n
        lda $2276
        sta spill_dp
        lda $75
        sta spill_lo
        lda $76
        sta spill_hi
@go:    ldx #$75                ; vwf_bmark,x: 1 = the BAT shows slot x (top or bottom tile)
@z:     stz vwf_bmark,x
        dex
        bpl @z
        jsr $E2D5
        lda #$01
        sta $18
        st0 #$01
        st1 #$00
        st2 #$00
        lda #$02
        sta $18
        st0 #$02
        stz $8E
        lda #$10
        sta $8F
@b:     lda a:$0002
        sec
        sbc $96
        tax
        lda a:$0003
        and #$0F
        sbc $97
        bne @bn
        txa
        lsr a
        cmp #$76
        bcs @bn
        tax
        lda #1
        sta vwf_bmark,x
@bn:    dec $8E
        bne @b
        dec $8F
        bne @b
        jsr vwf_spill_end       ; records go to the end of the group
        sta $8C
        sty $8D
        stz spill_cnt
        ldx #$75                ; candidates: finished VWF cells in use that the BAT does not show
@c:     lda vwf_bmark,x
        bne @cn
        lda vwf_open            ; not the cell being drawn
        beq @c1
        cpx vwf_slot
        beq @cn
@c1:    lda $285D,x
        cmp #$C0
        bcc @cn
        cmp #$FF
        beq @cn
        lda $28D3,x
        cmp #$C1
        bcc @cn
        cmp #$FF
        beq @cn
        lda spill_n
        cmp #SPILL_MAX
        bcs @cd
        ora #$80
        sta vwf_bmark,x         ; $80 + record index
        inc spill_n
        inc spill_cnt
        jsr vwf_rec_out
@cn:    dex
        bpl @c
@cd:    lda spill_cnt
        bne @wr
        sec
        rts
@wr:    lda #<spill_map         ; markers into the save stack under the records
        sta vwf_vec
        lda #>spill_map
        sta vwf_vec+1
        jsr vwf_walk
        ldx #$75                ; the spilled slots are free now
@f:     lda vwf_bmark,x
        bpl @fn
        lda $28D3,x
        and #$C0
        sta $28D3,x
@fn:    dex
        bpl @f
        jsr vwf_spill_end       ; the stack top moves past the records
        sta $75
        sty $76
        clc
        rts

; A/Y = VRAM address right after the records (spill_lo + 8 * spill_n).
vwf_spill_end:
        stz vwf_tmp
        lda spill_n
        asl a
        rol vwf_tmp
        asl a
        rol vwf_tmp
        asl a
        rol vwf_tmp
        clc
        adc spill_lo
        pha
        lda vwf_tmp
        adc spill_hi
        tay
        pla
        rts

; Copy main slot X (rows 0-7: low bytes of words 0-7 of the top tile, rows 8-15: of the bottom
; tile) to the record at $8C/$8D; $8C/$8D += 8. Keeps X. (VRAM to VRAM: reads through MARR and
; writes through MAWR interleaved, as the game's own $C295 does.)
vwf_rec_out:
        phx
        txa
        asl a
        clc
        adc $96
        sta vwf_tmp3
        cla
        adc $97
        sta $8B
        lda vwf_tmp3
        asl a
        rol $8B
        asl a
        rol $8B
        asl a
        rol $8B
        asl a
        rol $8B
        sta vwf_tmp3
        jsr $E2D5
        lda #$01                ; MARR = tile * 16
        sta $18
        st0 #$01
        lda vwf_tmp3
        sta a:$0002
        lda $8B
        sta a:$0003
        lda #$00                ; MAWR = record
        sta $18
        st0 #$00
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        jsr @pairs              ; top tile rows 0-7
        ldx #8                  ; words 8-15: planes 2/3
@sk:    lda a:$0002
        lda a:$0003
        dex
        bne @sk
        jsr @pairs              ; bottom tile rows 8-15
        lda $8C
        clc
        adc #8
        sta $8C
        bcc @r
        inc $8D
@r:     plx
        rts
@pairs: ldx #4
@p:     lda a:$0002             ; row 2k
        pha
        lda a:$0003
        lda a:$0002             ; row 2k+1
        tay
        lda a:$0003
        pla
        sta a:$0002
        sty a:$0003
        dex
        bne @p
        rts

; Walk the save stack words from $7100 up to spill_lo/hi and call (vwf_vec) with A = low, Y = high
; byte of each; a mapper that returns C=1 has the word replaced by A/Y. Uses $8C/$8D.
vwf_walk:
        jsr $E2D5
        stz $8C
        lda #$71
        sta $8D
@l:     lda $8C
        cmp spill_lo
        lda $8D
        sbc spill_hi
        bcs @r
        lda #$01
        sta $18
        st0 #$01
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        lda a:$0002
        ldy a:$0003
        jsr @call
        bcc @n
        pha
        lda #$00
        sta $18
        st0 #$00
        lda $8C
        sta a:$0002
        lda $8D
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        pla
        sta a:$0002
        sty a:$0003
@n:     inc $8C
        bne @l
        inc $8D
        bra @l
@r:     rts
@call:  jmp (vwf_vec)

; Mapper: a tile of a spilled main slot -> its marker (palette kept).
spill_map:
        sta vwf_tmp
        sec
        sbc $96
        tax
        tya
        and #$0F
        sbc $97
        bne @no
        txa
        lsr a
        cmp #$76
        bcs @no
        tax
        lda vwf_bmark,x
        bpl @no
        and #$3F                ; record index
        asl a
        ora #$80
        sta vwf_tmp3
        lda vwf_tmp             ; bottom tile: the cache base is even, so bit 0 of the tile
        and #$01
        ora vwf_tmp3
        pha
        tya
        and #$F0
        ora #MARK_HI
        tay
        pla
        sec
        rts
@no:    clc
        rts

; ---------------------------------------------------------------------------------------------
; Entry 6, from b03 $C406 (window close, after $C441 set $75/$76 back to the start of the closed
; window's save block, before $C295 copies that block back to the BAT): if the closed window made
; the spill group, every record that is still marked somewhere in the save stack gets a slot (main
; or extension, by the reference counts: the closed window's slots were released by $CF92, but the
; BAT still shows it, so no recount here) and its pixels again, with one reference per top marker, and all
; its markers are rewritten to that slot's tiles. Then the group is gone. Clobbers A X Y.
vwf_unspill:
        lda spill_n
        beq @r
        lda $2276
        cmp spill_dp
        bcc @go
@r:     rts
@go:    jsr vwf_finalize
        lda spill_n
        sta spill_cnt
        stz spill_n
        lda #1                  ; no recount (or spill) inside the allocations below: the BAT still
        sta vwf_gcoff           ; shows the closed window (its slots were released by $CF92 already)
        ldx #SPILL_MAX-1        ; vwf_bmark,i: top markers of record i (bit 7: a bottom marker seen)
@z:     stz vwf_bmark,x
        dex
        bpl @z
        lda #<us_count
        sta vwf_vec
        lda #>us_count
        sta vwf_vec+1
        jsr vwf_walk
        stz spill_i
@rec:   ldx spill_i
        lda vwf_bmark,x
        beq @none
        jsr vwf_take
        bcs @none
        jsr us_load
        jsr vwf_upload
        jsr vwf_hashcur
        ldx spill_i
        lda vwf_bmark,x
        and #$3F
        bne @c1
        lda #1
@c1:    ldy vwf_slot
        cpy #$80
        bcs @ex
        ora #$C0
        sta $28D3,y
        lda vwf_hash
        sta $285D,y
        bra @set
@ex:    pha
        tya
        and #$7F
        tay
        pla
        sta ext_ref,y
        lda vwf_hash
        sta ext_code,y
@set:   lda vwf_slot
        bra @st
@none:  lda #$FF
@st:    sta vwf_bmark,x
        inc spill_i
        lda spill_i
        cmp spill_cnt
        bne @rec
        stz vwf_open
        lda #<us_map
        sta vwf_vec
        lda #>us_map
        sta vwf_vec+1
        jsr vwf_walk
        jsr vwf_extcount
        stz vwf_gcoff
        rts

; Record spill_i -> vwf_cur.
us_load:
        lda spill_i
        stz $8B
        asl a
        rol $8B
        asl a
        rol $8B
        asl a
        rol $8B
        clc
        adc spill_lo
        sta vwf_tmp3
        lda $8B
        adc spill_hi
        sta $8B
        jsr $E2D5
        lda #$01
        sta $18
        st0 #$01
        lda vwf_tmp3
        sta a:$0002
        lda $8B
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        clx
@l:     lda a:$0002
        sta vwf_cur,x
        inx
        lda a:$0003
        sta vwf_cur,x
        inx
        cpx #16
        bne @l
        rts

; A/Y = a marker of the group? C=1: X = record index, vwf_tmp = 0 top / 1 bottom.
us_mark:
        sta vwf_tmp
        tya
        and #$0F
        cmp #MARK_HI
        bne @no
        lda vwf_tmp
        sec
        sbc #$80
        bcc @no
        lsr a
        cmp spill_cnt
        bcs @no
        tax
        lda vwf_tmp
        and #$01
        sta vwf_tmp
        sec
        rts
@no:    clc
        rts

; Mapper: count the markers per record.
us_count:
        jsr us_mark
        bcc @r
        lda vwf_tmp
        beq @t
        lda vwf_bmark,x
        ora #$80
        sta vwf_bmark,x
        bra @r
@t:     lda vwf_bmark,x
        and #$3F
        cmp #$3C
        bcs @r
        inc vwf_bmark,x
@r:     clc
        rts

; Mapper: a marker -> the tile of its record's new slot.
us_map:
        phy
        jsr us_mark
        ply
        bcc @r
        lda vwf_bmark,x
        cmp #$FF
        beq @n
        cmp #$80
        bcs @e
        asl a
        clc
        adc $96
        sta vwf_tmp3
        cla
        adc $97
        bra @t
@e:     and #$7F
        asl a
        clc
        adc #<EXT_TILE
        sta vwf_tmp3
        lda #>EXT_TILE
@t:     sta vwf_tmp2
        tya
        and #$F0
        ora vwf_tmp2
        tay
        lda vwf_tmp3
        ora vwf_tmp
        sec
        rts
@n:     clc
@r:     rts
