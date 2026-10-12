; title_b01.s -- title screen credit line (module gfx; region "gfx.b01", b01:$DE30-$DFFF).
; Hook b01:$C299 `jsr $C3DA` (load a planar image) -> jsr T_STUB. After image $1A (the title) is loaded,
; tile rows 26-28, columns 16-26 (tiles $450/$470/$490 + 0..10, colour 1 = plane 0 only) are rewritten from
; DATA (8 plane-0 bytes per tile, appended by tools/mod_gfx.py): "(C) Dynamic Pro" instead of the kana line.
NT = 11
MPR_PUSH = $E453
MPR_POP  = $E47E
MPR7BASE = $2200
; BG_COUNT > 0 (an edited gfx/title/title-bg.png): after the credit line, asm/title_bg_far.s (bank GFX_BANK
; at $7000, MPR3) re-draws the changed background tiles.

.segment "CODE"
T_STUB:
        phx
        jsr $C3DA
        plx
        cpx #$1A
        beq @go
        jmp @r
@go:
        lda $00
        pha
        lda $01
        pha
        lda #<DATA
        sta $00
        lda #>DATA
        sta $01
        clx
@row:   lda #$00
        sta $18
        st0 #$00
        lda ADDR,x
        sta a:$0002
        lda ADDR+1,x
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        phx
        ldx #NT
@tile:  ldy #8
@p0:    lda ($00)
        sta a:$0002
        stz a:$0003
        inc $00
        bne @n
        inc $01
@n:     dey
        bne @p0
        ldy #8
@p2:    stz a:$0002
        stz a:$0003
        dey
        bne @p2
        dex
        bne @tile
        plx
        inx
        inx
        cpx #6
        bne @row
.if BG_COUNT > 0
        jsr MPR_PUSH
        lda #GFX_BANK
        clc
        adc MPR7BASE
        tam #$08
        jsr $7000               ; asm/title_bg_far.s
        jsr MPR_POP
.endif
        pla
        sta $01
        pla
        sta $00
@r:     rts
.if LOGO_LIST > 0
; edited logo: hook b01 $CA85 `jsr $CB34` (draw a sprite list). For the title logo's list table ($3A = $D83B)
; make sure the new patterns are in VRAM (bank UPL_BANK), then draw the new layout (asm/logo_list_far.s at $6000
; in bank LIST_BANK); anything else -> $CB34.
L_STUB:
        lda $3A
        cmp #$3B
        bne @o
        lda $3B
        cmp #$D8
        bne @o
        jsr MPR_PUSH
        lda #UPL_BANK
        clc
        adc MPR7BASE
        tam #$08
        jsr $6000               ; LGU_ENTRY (asm/logo_upload_far.s): patterns still ours?
        lda #LIST_BANK
        clc
        adc MPR7BASE
        tam #$08
        jsr $6000               ; LGF_LIST
        jsr MPR_POP
        rts
@o:     jmp $CB34
.endif
ADDR:   .word $4500, $4700, $4900
DATA:
