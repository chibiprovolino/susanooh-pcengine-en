; skip_b00.s -- battle text option, bank 0 stubs (module skip; region "skip.b00", b00:$FF90-$FFF5).
; Option "Battle Messages" ($2784, 13:014/13:017): 0 Normal, 1 Press to skip, 2 Off (= the original Hide).
; FLAG $26C0, set only in Press to skip by the gate (asm/skip_b06.s) when a gated battle message starts,
; cleared when the top window closes: bit7 = skippable battle message, bit4 = fast (I/II pressed or held
; during the message: the rest prints instantly). In Press to skip every [0F] pause waits for a fresh press
; (no timer, no release wait). Normal never sets FLAG, so the stubs then do exactly what the original
; code did.
; Hooks (tools/mod_skip.py, original bytes asserted):
;   b03:$CEC7 `bbs1 $98,$CEDF`       -> jsr D_STUB  (per-character delay)
;   b03:$CB90 `ldy $2783/ldx $DE5E,y`-> jsr P_STUB + 3 nop ([0F] pause)
;   b00:$EECD `ldx #$0A / jsr`       -> jmp E_STUB  (close the top window)
;   b03:$CA99 `smb1 $98 / rts`       -> jmp W_STUB  (end of $CA8F: start of every 0B/0E wait and menu)
;   b00:$F136 `ldx $2783`            -> jsr F_STUB  (speed set when an EED3 window opens)
; Text skip for all other messages (always on): while field/event/shop/menu text prints with a
; delay, a fresh press of I or II (consumed) sets FLAG bit3 and the rest of the page prints at once; bit3 is
; cleared at the next 0B/0E wait or menu ($CA8F), when an EED3 window opens and when the top window closes,
; so the next press advances or answers as usual. Not used for cutscenes (cache base $2C = $50) or for gated
; battle messages in Normal (the gate sets FLAG bit5 there) or Press to skip (bit7).

FLAG = $26C0

.segment "CODE"
; Per-character delay. In a skippable battle message, a fresh press of I/II (consumed, so it does not also
; end the pause) or a held button makes the message fast: the rest prints with no delay ($92 = 0).
; Then the original `bbs1 $98,<rts>` (no delay at all when bit 1 of $98 is set).
D_STUB:
        lda FLAG
        bpl @field              ; not a skippable battle message
        and #$10
        bne @orig               ; already fast ($92 is 0)
        lda $2213               ; presses latched since the last read
        and #$03
        beq @held
        trb $2213
        bra @set
@held:  lda $2209               ; buttons held now
        and #$03
        beq @orig
@set:   lda #$10
        tsb FLAG
        stz $92
@orig:  bbr1 $98, @r
@skip:  pla
        pla
@r:     rts
@field: bbs1 $98, @skip          ; menu/wait cursor drawing: no delay, and never touch its presses
        bit #$20
        bne @orig               ; gated battle message in Normal: the original pacing
        bit #$08
        bne @skip               ; this page is being completed: no delay
        lda $92
        beq @orig               ; no delay anyway: leave the presses alone
        lda $2C
        cmp #$20
        bne @orig               ; cutscene (glyph cache at $50A)
        lda $2213               ; fresh I/II press: consume it, print the rest of the page at once
        and #$03
        beq @orig
        trb $2213
        lda #$08
        tsb FLAG
        bra @skip

; End of $CA8F (pen saved for the cursor; every 0B/0E wait and menu starts with it): the page is complete,
; the next press works as usual. Keeps A.
W_STUB:
        pha
        lda #$08
        trb FLAG
        pla
        smb1 $98
        rts

; 0B/0E wait (b03 $CB5D): the wait loop draws the blinking cursor through the print routine with
; $98 bit1 clear ($CA9C), so D_STUB took the first press of the wait as a press-to-finish and swallowed it.
; FLAG bit3 is set for the whole wait (cursor draws: no delay, presses untouched) and cleared at its end.
X_STUB:
        jsr $CA8F
        lda #$08
        tsb FLAG
        rts
; End of the 0B/0E wait (b03 $CB78 `jsr $CA9C`).
Y_STUB:
        lda #$08
        trb FLAG
        jmp $CA9C

; Speed set when an EED3 window opens ($F136): a new window prints at the normal speed.
F_STUB:
        lda #$08
        trb FLAG
        ldx $2783
        rts

; [0F] pause. Original ($CB90-$CBAF): X = $DE5E[$2783] frames, a fresh press ends it, then wait until
; I/II are released. Skippable battle message (Press to skip): no timer, the message stays until a
; fresh I/II press (consumed; no release wait). A press that made the message fast was consumed in D_STUB, so
; it never also closes the message. Returns from the [0F] handler (pla pla rts).
P_STUB:
        ldy $2783
        ldx $DE5E,y
        lda FLAG
        bpl @r                  ; not a skippable message: original pause
@l:     jsr $E257               ; wait for vsync
        jsr $E327               ; A = fresh presses (and clears them)
        and #$03
        beq @l
        pla
        pla
@r:     rts

; Close the top window: FLAG = 0, then the original `ldx #$0A / jsr $E579 / rts`.
E_STUB:
        stz FLAG
        ldx #$0A
        jmp $E579
