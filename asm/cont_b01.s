; cont_b01.s -- continuation code `03 n` for the bank 1 cutscene/script print loop. Module: text.
; Region "text.b01" (bank 1, $DDD4-$DFFF). Hook (mod_text.py):
;   b01:$C86A `lda $26FD,x / bne $C872 / jmp $C6AC` -> `jsr TEXT_B1CHK / bcc $C872 / jmp $C6AC`
; X = index into $26FD. C=1: end (00). C=0: A = byte to print; after a refill X = 0.
; This loop never had a $91 (argument) test: an argument 00 ends the string as before, and the inserter
; never emits 00, 03 or 1F as an argument. TEXT_REFILL (cont_b00.s, bank 0) keeps $71-$73 and $08/$09.

LINEBUF  = $26FD

.segment "CODE"
TEXT_B1CHK:
        lda LINEBUF,x
        beq @end
        cmp #$03
        beq @cont
        clc
        rts
@end:   sec
        rts
@cont:  phy
        lda LINEBUF+1,x         ; n
        jsr TEXT_REFILL
        ply
        ldx #0
        bra TEXT_B1CHK
