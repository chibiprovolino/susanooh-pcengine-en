; ui_b00.s -- UI string helpers in bank 0 (module ui; region "ui.b00", b00:$FEC0-$FF5F).
; docs/design.md.
;
; PSTR   `jsr PSTR / .dw ptr / <filler, non-zero> / 00`
;        Replaces an inline `jsr $EF5F / <string> / 00` whose English does not fit. ptr = a string in
;        bank UI_BANK at $6000-$7FFF (MPR3). Copies it to the line buffer $26FD, returns after the
;        original 00 (so every code address stays where it was) and prints it like $EF5F ($EF39).
; UIFAR  `jsr UIFAR / .dw target`
;        Far call: maps bank UI_BANK at MPR3 ($6000, MPR2-6 saved by $E453 and restored by $E47E) and
;        calls target ($6000-$7FFF) with A, X, Y and the flags of the caller; returns after the .dw
;        with A, X, Y and the flags the target left. The caller's bank stays at MPR6, so the far code
;        can call the caller's own routines.
; SHOPNAME `jsr SHOPNAME` in place of `jsr $F052` in the shop buy list row (b07 $C9D7): prints the item
;        name, then, if the VWF pen stopped just past a cell boundary with nothing drawn in that cell (a
;        name of 81 px: its last pixel column is the blank gap after the last letter), puts the pen back
;        on that cell boundary, so the price that follows at the explicit column 12 stays in column 12.
; Defines from tools/mod_ui.py: UI_BANK.
; RAM $2650-$265F belongs to ui (docs/design.md §2).

UI_V     = $2650                ; 2 bytes: target / string pointer
UI_A     = $2652
UI_X     = $2653
UI_Y     = $2654
UI_P     = $2655
MPR_PUSH = $E453
MPR_POP  = $E47E
LINEBUF  = $26FD
VWF_PX   = $2605                ; asm/vwf_ram.inc vwf_px / vwf_open
VWF_OPEN = $2606
PRINTBUF = $EF39
MPR7BASE = $2200

.segment "CODE"
PSTR:
        jsr getarg
        tsx
@scan:  iny                     ; skip the filler up to the original 0
        lda ($16),y
        bne @scan
        tya
        clc
        adc $16
        sta $2101,x             ; return to the 0 (+1 by rts)
        cla
        adc $17
        sta $2102,x
        jsr mapui
        lda UI_V
        sta $16
        lda UI_V+1
        sta $17
        cly
@copy:  lda ($16),y             ; <= 111 bytes, checked by the build
        sta LINEBUF,y
        beq @done
        iny
        bra @copy
@done:  jsr MPR_POP
        jmp PRINTBUF

UIFAR:
        php
        sta UI_A
        stx UI_X
        sty UI_Y
        pla
        sta UI_P
        jsr getarg
        tsx
        lda $16                 ; return after the .dw
        clc
        adc #2
        sta $2101,x
        bcc @nc
        inc $2102,x
@nc:    jsr mapui
        lda UI_P
        pha
        lda UI_A
        ldx UI_X
        ldy UI_Y
        plp
        jsr @go
        jmp MPR_POP             ; keeps A, X, Y and the flags
@go:    jmp (UI_V)

; ($16) = the caller's return address (last byte of its jsr), UI_V = the .dw after it, Y = 2.
; $16/$17 are the scratch of the game's own inline readers ($EF5F, $EEED); nothing keeps a value there.
getarg: tsx
        lda $2103,x
        sta $16
        lda $2104,x
        sta $17
        ldy #1
        lda ($16),y
        sta UI_V
        iny
        lda ($16),y
        sta UI_V+1
        rts

SHOPNAME:
        jsr $F052
        lda VWF_OPEN
        bne @r
        stz VWF_PX
@r:     rts

mapui:  jsr MPR_PUSH            ; MPR2-6 saved; bank UI_BANK at MPR3
        lda #UI_BANK
        clc
        adc MPR7BASE
        tam #$08
        rts
