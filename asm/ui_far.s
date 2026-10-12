; ui_far.s -- reordered UI messages, bank UI_BANK ($58) at MPR3 = $6000 (module ui).
; Entered through UIFAR (asm/ui_b00.s): the caller's bank stays at MPR6 ($C000), so each routine below
; may call routines of the bank it was patched into (noted per routine) and of bank 0.
; The S_* strings are laid out by tools/mod_ui.py from translation/en_inline.tsv (and 13:019) at $7000+
; and passed as defines; every one is 04 ... 05 (VWF) unless noted.
;
; Bank 0 routines used: $EF31 putc A, $EF2F putc digit, $EF39 print $26FD, $EF41 print ($34),
;   $F076 name (block $15), $F052 item (block $14), $F048 ESP (block $12), $F03E place (block $11),
;   $F3F1/$F45E 16-bit $08/$09 -> left-justified digits in $26FD, $E80F/$E721 (gold), $D08D (bank 9 loop).

PUTC   = $EF31
PRBUF  = $EF39
PRPTR  = $EF41

.macro PRINT addr
        lda #<addr
        sta $34
        lda #>addr
        sta $35
        jsr PRPTR
.endmacro

.segment "CODE"

; ---- shared helpers ------------------------------------------------------------------------------
; "Susa" or "Susa and party" (was $F05C without its topic marker は).
party:
        cla
        jsr $F076
        lda $229E
        and $229F
        bmi @solo
        PRINT S_AND_PARTY
@solo:  rts

; Number in $08/$09, no leading zeros, drawn proportionally (04 ... 05 around the digits).
pnum:
        lda #$04
        jsr PUTC
        jsr $F3F1
        jsr $F45E
        jsr PRBUF
        lda #$05
        jmp PUTC

; ---- bank 2: "<party> gained <N> EXP." / "... GOLD." (was b02:$D3BD-$D3D2) ------------------------
gain2:
        jsr party
        PRINT S_GAINED
        lda $2CCD
        sta $08
        lda $2CCE
        sta $09
        jsr pnum
        lda $2E7F
        bne @gold
        PRINT S_EXP_END
        rts
@gold:  PRINT S_GOLD_END
        rts

; ---- bank 6: "<party> gained <N> EXP and <N> GOLD." (was b06:$DABC-$DAE1) -----------------------
victory:
        jsr party
        PRINT S_GAINED6
        lda $2CBF
        sta $08
        stz $09
        jsr pnum
        PRINT S_EXP_AND
        lda $2CC0
        sta $08
        stz $09
        jsr pnum
        PRINT S_GOLD_END6
        rts

; ---- bank 7: "<party> found <N> GOLD." (was b07:$D744-$D786, uses the bank 7 table $D787) -------
found:
        jsr party
        PRINT S_FOUND
        ldx $2790
        lda $D787,x
        ldx #$0A
        jsr $E80F
        lda $0E
        sta $08
        pha
        lda $0F
        sta $09
        pha
        jsr pnum
        PRINT S_GOLD_FOUND
        pla
        sta $0F
        pla
        sta $0E
        ldx #$0A
        jsr $E721               ; add the gold (as the original did before its [0E])
        PRINT S_FOUND_END
        rts

; ---- bank 7: "<party> obtained <item>." (was b07:$D852-$D869) ------------------------------------
obtain:
        jsr party
        PRINT S_OBTAINED
        lda $2E81
        jsr $F052
        PRINT S_OBTAIN_END
        rts

; ---- bank 5: "<party> teleported to <vehicle|place|Outside>." (was b05:$D18C/$D1A6/$D1C0) ------
tele_v:
        jsr party
        PRINT S_TELE
        ldx $2785
        lda $FAE9,x
        jsr $F076
        bra tele_end
tele_p:
        jsr party
        PRINT S_TELE
        ldx $2780
        lda $FABF,x
        jsr $F03E
        bra tele_end
tele_o:                                 ; "<party> teleported outside." (no "to")
        jsr party
        PRINT S_TELE_O
        PRINT S_OUTSIDE
tele_end:
        PRINT S_TELE_END
        rts

; ---- bank 7 level-up: "<stat> rose by <N>." / "fell by" (was b07:$D3D3; A = value, C as there) ----
lvdiff:
        bcs @fell
        eor #$FF
        inc a
        sta $08
        stz $09
        PRINT S_ROSE
        bra @num
@fell:  sta $08
        stz $09
        PRINT S_FELL
@num:   jsr pnum
        PRINT S_LV_END
        rts

; ---- bank 7: "Level <n> <ESP> can now be used." (was b07:$D3FF-$D43A; Y = ESP index) -------------
esplearn:
        phy
        jsr $D35F               ; bank 7: window + "<name>'s " or a new line
        ply
        phy
        cpy #$06
        bcs @name
        PRINT S_LEVEL
        lda #$04
        jsr PUTC
        ply
        phy
        lda $2776,y
        jsr $EF2F
        lda #$05
        jsr PUTC
        PRINT S_LVSEP
@name:  pla
        jsr $F048
        PRINT S_CANUSE
        rts

; ---- bank 9 equipment labels (were 1-byte kanji 武 鎧 盾 兜 力 after jsr $EF5F) ---------------------
lbl_wpn:
        PRINT S_WPN
        rts
lbl_arm:
        PRINT S_ARM
        rts
lbl_shd:
        PRINT S_SHD
        rts
lbl_hlm:
        PRINT S_HLM
        rts
lbl_str:
        PRINT S_STRL
        rts

; ---- bank 9 password screen: "Please enter <label>." / "<label> value is too large." ------------
; $34/$35 = the label pointer the original code set up (one of PW_L0..PW_L5 in bank 9).
; The sentences are precomposed and centred with 15 n (tables PW_TAB_P / PW_TAB_L below).
pwprompt:
        jsr pwfind
        lda PW_TAB_P,x
        sta $34
        lda PW_TAB_P+1,x
        sta $35
        jmp $D08D
pwlarge:
        jsr pwfind
        lda PW_TAB_L,x
        sta $34
        lda PW_TAB_L+1,x
        sta $35
        jmp $D08D
pwfind:                         ; X = 2 * index of the label ($34/$35), 0 if unknown
        ldx #10
@l:     lda PW_LBL,x
        cmp $34
        bne @n
        lda PW_LBL+1,x
        cmp $35
        beq @f
@n:     dex
        dex
        bpl @l
        ldx #0
@f:     rts
PW_LBL:   .word PW_L0, PW_L1, PW_L2, PW_L3, PW_L4, PW_L5
PW_TAB_P: .word S_PWP0, S_PWP1, S_PWP2, S_PWP3, S_PWP4, S_PWP5
PW_TAB_L: .word S_PWL0, S_PWL1, S_PWL2, S_PWL3, S_PWL4, S_PWL4

; ---- bank 9 backup-memory / continue messages (CD-ROM2 only; were lda/sta $34/$35 + print) ------
bk_c400:
        PRINT S_BK_C400
        rts
bk_c42c:
        PRINT S_BK_C42C
        rts
bk_c440:
        PRINT S_BK_C440
        rts
bk_c47c:
        PRINT S_BK_C47C
        rts
bk_c4b5:
        PRINT S_BK_C4B5
        rts
bk_c4d4:
        PRINT S_BK_C4D4
        rts
cont_d5d5:
        lda #<S_CO_D5D5
        sta $34
        lda #>S_CO_D5D5
        sta $35
        jmp $D08D
cont_d614:
        lda #<S_CO_D614
        sta $34
        lda #>S_CO_D614
        sta $35
        jmp $D08D

; ---- bank 9: menu-only short names (translation/short-names.tsv) --------------
; Called through the bank 9 stubs SHORTI / SHORTP (region ui.b09) from the narrow name fields: status page 2
; and the single-member equip window ($DA44), the item bag ($DB21/$DB31), the teleport list ($DE0D).
; A = item (block $14) / place (block $11) index. SHORT_I / SHORT_P: one word per index, the short name
; in this bank or 0 (high byte 0 = none): then the full name is printed as before ($F052 / $F03E).
short_item:
        cmp #NITEMS
        bcs @full
        pha
        asl a
        tax
        lda SHORT_I+1,x
        beq @none
        sta $35
        lda SHORT_I,x
        sta $34
        pla
        jmp PRPTR
@none:  pla
@full:  jmp $F052

short_place:
        cmp #NPLACES
        bcs @full
        pha
        asl a
        tax
        lda SHORT_P+1,x
        beq @none
        sta $35
        lda SHORT_P,x
        sta $34
        pla
        jmp PRPTR
@none:  pla
@full:  jmp $F03E

; ---- bank 9: text options kept in backup memory ------------------------------------
; The BRAM file "SUSA.NO.OH" is the $8B-byte block at $3318: byte 0 = used-slot bits 0-2 ($C195,x), then 3 x $2E
; bytes of slot data. Bits 3-7 of byte 0 were always 0; they now hold the text options of the last save:
; bits 3-5 = message speed $2783 (0-4), bits 6-7 = battle text $2784 + 1 (1-3; 0 = an older save, nothing stored).
; opt_save replaces `lda $C195,x / ora $3318 / sta $3318` (b09 $C1AA, save, X = slot).
; opt_load runs before `lda #$2E / jsr $E80F` (b09 $C16B, load of a used slot, X = slot); X is kept.
opt_save:
        lda $3318
        and #$07
        ora $C195,x
        sta $3318
        lda $2784
        inc a
        and #$03
        asl a
        asl a
        asl a
        asl a
        asl a
        asl a
        tsb $3318
        lda $2783
        and #$07
        asl a
        asl a
        asl a
        tsb $3318
        rts

opt_load:
        lda $3318
        and #$C0
        beq @old
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        lsr a
        dec a
        sta $2784
        lda $3318
        lsr a
        lsr a
        lsr a
        and #$07
        cmp #$05
        bcs @old
        sta $2783
@old:   lda #$2E
        jmp $E80F

; Load list (b09 $C5AE, replaces `tax / lda $32E3,x / sta $2797`): A = the chosen row, counting used slots only.
; The original looked it up in $32E3, which is indexed by slot (rows of empty slots are never written), so with
; slot 1 empty, loading slot 2 or 3 read a stale index and started a blank game (also in the Japanese original).
; Here: $2797 = A = the slot of the A-th set bit of the slot bits $32DE (3 = none, which the load rejects).
load_pick:
        tay
        lda $32DE
        ldx #$FF
@loop:  inx
        cpx #$03
        bcs @done
        lsr a
        bcc @loop
        dey
        bpl @loop
@done:  stx $2797
        txa                     ; A = slot, as the original left it for the load call
        rts
