; skip_b06.s -- battle message gate (module skip; region "skip.b06", b06:$DC89-$DC9E).
; Hook b06:$C8A4 `lda $2784` -> jmp GATE. The original gate was `lda $2784 / beq +2 / pla / pla / rts`:
; non-zero returned from the caller (message hidden). Now: 0 Normal -> the original (shown; FLAG $20 so the
; general text skip leaves it alone),
; 1 Press to skip -> shown and skippable, then held until a press (FLAG $80 until the window closes, skip_b00.s),
; 2 Off -> hidden exactly as the original Hide.
FLAG = $26C0

.segment "CODE"
GATE:
        lda $2784
        cmp #$02
        bcs @off
        lsr a                   ; C = 1: Press to skip
        lda #$20                ; Normal: FLAG bit5 = battle message, no tap-to-complete (skip_b00.s)
        bcc @s
        lda #$80
@s:     sta FLAG
        rts
@off:   pla
        pla
        rts
