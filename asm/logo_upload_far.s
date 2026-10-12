; logo_upload_far.s -- edited title logo patterns (module gfx; bank "gfx.far" second bank, $6000 via MPR3).
; Called every frame the logo list is drawn (L_STUB, asm/title_b01.s), i.e. on the title screen and at the end
; of the opening. Checks one word per logo cell in VRAM (LGU_SIG: LGU_N x (VRAM address, word)); if any differs
; (the game has just decoded its own logo object $60 there) re-uploads all cells from LGU_CELLS: CNT_A cells to
; VRAM $6000 (cells 0-28), CNT_B cells to $6C00 (cells 48-63). Cell 29 ($6740, START cursor) is not touched.
; (Playtest 5 hooked the decoder (b04 $C2AD, object test $A9 = $60) instead: that also fired for the
; opening's own sprites and overwrote them.)
.segment "CODE"
LGU_ENTRY:
        clx
@chk:   lda #$01
        sta $18
        st0 #$01                ; MARR
        lda LGU_SIG,x
        sta a:$0002
        lda LGU_SIG+1,x
        sta a:$0003
        lda #$02
        sta $18
        st0 #$02
        lda a:$0002
        cmp LGU_SIG+2,x
        bne LGU_UP
        lda a:$0003
        cmp LGU_SIG+3,x
        bne LGU_UP
        inx
        inx
        inx
        inx
        cpx #(LGU_N * 4)
        bne @chk
        rts

LGU_UP:
        lda $00
        pha
        lda $01
        pha
        lda #<LGU_CELLS
        sta $00
        lda #>LGU_CELLS
        sta $01
        lda #$60
        ldx #CNT_A
        jsr LGU_RUN
.if CNT_B > 0
        lda #$6C
        ldx #CNT_B
        jsr LGU_RUN
.endif
        pla
        sta $01
        pla
        sta $00
        rts

LGU_RUN:                        ; A = VRAM address high byte, X = cells; source ($00) advances
        pha
        lda #$00
        sta $18
        st0 #$00
        stz a:$0002
        pla
        sta a:$0003             ; MAWR
        lda #$02
        sta $18
        st0 #$02
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
LGU_SIG:
