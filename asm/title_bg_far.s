; title_bg_far.s -- edited title background tiles (module gfx; bank "gfx.far" at $7000 = offset $1000, MPR3).
; Called from asm/title_b01.s only when gfx/title/title-bg.png was edited. BGF_DATA: BG_COUNT entries of 10 bytes,
; VRAM word address + 8 plane-0 bytes (planes 1-3 written as zero). Uses $00-$03 (the caller saved $00/$01).
.segment "CODE"
BGF_ENTRY:
        lda $02
        pha
        lda $03
        pha
        lda #<BGF_DATA
        sta $00
        lda #>BGF_DATA
        sta $01
        lda #<BG_COUNT
        sta $02
        lda #>BG_COUNT
        sta $03
@bt:    lda #$00
        sta $18
        st0 #$00
        lda ($00)
        sta a:$0002
        ldy #1
        lda ($00),y
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        iny
@bp:    lda ($00),y
        sta a:$0002
        stz a:$0003
        iny
        cpy #10
        bne @bp
        ldy #8
@bz:    stz a:$0002
        stz a:$0003
        dey
        bne @bz
        lda $00
        clc
        adc #10
        sta $00
        bcc @bn
        inc $01
@bn:    lda $02
        bne @bd
        dec $03
@bd:    dec $02
        lda $02
        ora $03
        bne @bt
        pla
        sta $03
        pla
        sta $02
        rts
BGF_DATA:
