; logo_list_far.s -- sprite list for an edited title logo (module gfx; bank "gfx.far" first bank, $6000 via MPR3).
; The title logo is drawn each frame by b01 $CB34 from one of 16 lists (table b01 $D83B, one per fade step,
; identical but for the palette byte): count, 2 bytes = 4 palette nibbles, count x (y, x, cell|pal<<6, attr hi).
; L_STUB (asm/title_b01.s, hook b01 $CA85 `jsr $CB34`) calls LGF_LIST instead for the logo table: the palette
; nibbles still come from the original list at ($3C); the entries come from LGF_ENT (LGF_N x 4 bytes, appended
; by tools/mod_gfx.py), drawn by the original loop at b01 $CB60. $3C is left as the original routine leaves it.
.segment "CODE"
LGF_LIST:
        lda $3C
        pha
        lda $3D
        pha
        ldy #1
        clx
@p:     lda ($3C),y
        pha
        lsr
        lsr
        lsr
        lsr
        sta $281C,x
        inx
        pla
        and #$0F
        sta $281C,x
        inx
        iny
        cpx #4
        bne @p
        lda #<LGF_ENT
        sta $3C
        lda #>LGF_ENT
        sta $3D
        lda #LGF_N
        jsr $CB60               ; the original entry loop (pha count ... pla/dec/bne ... rts)
        pla
        sta $3D
        pla
        clc
        adc #(3 + 4 * 11)       ; past the original 11-entry list, as $CB34 leaves it
        sta $3C
        bcc @n
        inc $3D
@n:     rts
LGF_ENT:
