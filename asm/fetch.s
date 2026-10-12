; fetch.s -- new string FETCH (design B, docs/design.md). Module: text.
; Assembled by tools/mod_text.py into region "text.b38" (bank $38, CPU $DE73-$DFFF).
; Hook: b38:$C687 `pha / jsr $E453` -> `jmp TEXT_FETCH` (the old Huffman fetch body becomes dead code).
;
; Entry (all three callers fall into or bsr to $C687): A = string index, $72 = block number
;   (the block table b38:$C75C holds (block, 0) words, so $C669/$C66E store the block in $72), $71 = write index.
; Exit: string copied to $26FD+$71 with its 0; $71 = index of the 0; MPR2-6 restored; A = 0, Y = 0, X = $71.
; Index (bank IDX_BANK at $6000): directory of 3-byte entries (bank, lo, hi) per block -> the block's table of
;   3-byte entries (bank, lo, hi) per string; string address in $6000-$7FFF, bank+1 mapped at $8000 so a string
;   may cross one bank boundary. Zero page used: $08/$09 (the old plain-mode pointer; CHK saves it).
; Defines from mod_text.py: IDX_BANK.

MPR_PUSH = $E453
MPR_POP  = $E47E
LINEBUF  = $26FD
MPR7BASE = $2200                ; MPR7 at reset (0 on a HuCard); the engine adds it to every bank number

.segment "CODE"
TEXT_FETCH:
        pha                     ; string index
        jsr MPR_PUSH
        lda #IDX_BANK
        clc
        adc MPR7BASE
        tam #$08                ; MPR3 = index bank
        lda $72                 ; block (< $56, so 3*block fits in 8 bits)
        asl a
        adc $72
        tax
        lda $6001,x             ; this block's table
        sta $08
        lda $6002,x
        sta $09
        lda $6000,x
        clc
        adc MPR7BASE
        tam #$08
        pla                     ; ($08) += 3 * index
        pha
        asl a
        bcc :+
        inc $09
:       clc
        adc $08
        sta $08
        bcc :+
        inc $09
:       pla
        clc
        adc $08
        sta $08
        bcc :+
        inc $09
:       lda ($08)               ; string bank
        pha
        ldy #1
        lda ($08),y
        tax
        iny
        lda ($08),y
        sta $09
        stx $08
        pla
        clc
        adc MPR7BASE
        tam #$08                ; MPR3 = string bank
        inc a
        tam #$10                ; MPR4 = next bank
        ldx $71
        cly
@copy:  lda ($08),y
        sta LINEBUF,x
        beq @done
        cpx #$6F                ; index 111 = last byte of the buffer ($276C): force the end there
        beq @full
        inx
        iny
        bra @copy
@full:  stz LINEBUF,x           ; unreachable with inserter-checked strings (<= 111 bytes per fetch)
@done:  stx $71
        jsr MPR_POP
        cla
        cly
        rts
