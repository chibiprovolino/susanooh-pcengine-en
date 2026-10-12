; logo_b04.s -- title logo sprite patterns (module gfx; region "gfx.b04", b04:$DED1-$DFFF).
; The 凄ノ王伝説 logo is sprite object $60, loaded by the compressed-sprite loader (b04 $C27A) into VRAM
; words $6000-$673F (29 cells of 16x16, 4 planes). Hook b04:$C2AD `jsr $C2DA` -> G_STUB: after the object
; is fully decoded (several frames), object $60's patterns are overwritten with the English logo from
; LOGO_BANK (mapped at MPR3).
; CNT_A cells go to VRAM $6000 (cells 0-28; cell 29 is the START cursor), then CNT_B cells to $6C00.
; Hook: b04:$C2AD `jsr $C2DA` (the decode loop; it runs to the end of the object).
MPR_PUSH = $E453
MPR_POP  = $E47E
MPR7BASE = $2200

.segment "CODE"
G_STUB:
        jsr $C2DA
        php
        pha
        phx
        phy
        lda $A9
        cmp #$60                ; the title logo?
        bne @done
        jsr UPLOAD
@done:  ply
        plx
        pla
        plp
        rts

UPLOAD:
        lda $00
        pha
        lda $01
        pha
        jsr MPR_PUSH
        lda #LOGO_BANK
        clc
        adc MPR7BASE
        tam #$08                ; MPR3 = logo bank at $6000
        lda #$00
        sta $18
        st0 #$00
        stz a:$0002
        lda #$60
        sta a:$0003             ; MAWR = $6000
        lda #$02
        sta $18
        st0 #$02
        stz $00
        lda #$60
        sta $01
        ldx #CNT_A              ; cells 0.. at VRAM $6000, 128 bytes each
        jsr @run
.if CNT_B > 0
        lda #$00
        sta $18
        st0 #$00
        stz a:$0002
        lda #$6C
        sta a:$0003             ; MAWR = $6C00 (cells 48-63, free on the title screen)
        lda #$02
        sta $18
        st0 #$02
        ldx #CNT_B
        jsr @run
.endif
        jsr MPR_POP
        pla
        sta $01
        pla
        sta $00
        rts
@run:
@cell:  cly
@byte:  lda ($00),y
        sta a:$0002
        iny
        lda ($00),y
        sta a:$0003
        iny
        cpy #$80
        bne @byte
        lda $00
        clc
        adc #$80
        sta $00
        bcc @nc
        inc $01
@nc:    dex
        bne @cell
        rts
