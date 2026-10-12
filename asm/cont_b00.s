; cont_b00.s -- continuation code `03 n` for the bank 0 print loop and the shop loop. Module: text.
; Region "text.chk" (bank 0, $FE30-$FEBF). docs/design.md.
; Hooks (mod_text.py):
;   b00:$EF46 `bbs7 $91,$EF4D / cmp #0 / beq $EF58` -> `jsr TEXT_CHK / bcs $EF58 / nop nop`
;   b07:$C192 `cmp #0 / beq $C1BD / cmp #$5F / bne $C1B2` -> `jsr TEXT_CHKS / bcs $C1BD / bne $C1B2 / nop`
; `03 n` ends a piece; the rest of the string is piece n of block $21. The refill fetches it into $26FD with
; the normal fetch (E566 X=$0A) and keeps $71-$73 (the bank 1 script's "current block") and $08/$09
; (FETCH's pointer) in RAM $2640-$2644, so callers see no change.

FAR38    = $E566
LINEBUF  = $26FD
CONTSAVE = $2640                ; $2640-$264F reserved for text (docs/design.md §2); 5 bytes used
CONTBLK  = $21

.segment "CODE"
; A = byte at ($34). C=1: end of string. C=0: print A (after a refill, A is the next piece's first byte).
TEXT_CHK:
        bbs7 $91, @chr          ; argument of a 2-byte code: always printed (keeps the original rule)
        cmp #$00
        beq @end
        cmp #$03
        beq @cont
@chr:   clc
        rts
@end:   sec
        rts
@cont:  phx
        phy
        ldy #1
        lda ($34),y             ; n
        jsr TEXT_REFILL
        ply
        plx
        lda #<LINEBUF
        sta $34
        lda #>LINEBUF
        sta $35
        lda ($34)
        bra TEXT_CHK

; Shop loop (b07:$C182) variant; its own bbs7 $91 test runs before. C=1: end; else C=0, A = byte,
; Z=1 when A is the price placeholder $5F.
TEXT_CHKS:
        jsr TEXT_CHK
        bcs @e
        cmp #$5F
        clc
@e:     rts

; Fetch piece A of block $21 into $26FD (index 0). Clobbers A, X, Y.
TEXT_REFILL:
        pha
        lda $71
        sta CONTSAVE
        lda $72
        sta CONTSAVE+1
        lda $73
        sta CONTSAVE+2
        lda $08
        sta CONTSAVE+3
        lda $09
        sta CONTSAVE+4
        pla
        ldy #CONTBLK
        ldx #$0A
        jsr FAR38
        lda CONTSAVE
        sta $71
        lda CONTSAVE+1
        sta $72
        lda CONTSAVE+2
        sta $73
        lda CONTSAVE+3
        sta $08
        lda CONTSAVE+4
        sta $09
        rts
