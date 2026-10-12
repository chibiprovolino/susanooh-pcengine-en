# Unused lines

According to the developer interview on the April 1989 issue of Marukatsu PC-Engine, the game had a lot of content cut in order to fit a 4Mbit cart. You can see a lot of unused fragments of cutscenes in the ending credits, including sequences that don't fit the current game's plot,
but there's not much more left. A dialogue in Island Town points to a significant story difference, and is listed below with other less significant cut dialogue just for fun.

Found with `tools/evscan.py` on the Japanese ROM. These are lines of the original game that nothing prints. They are translated anyway.


## Island Town (block 0A)

| Line | Japanese | English | Why it's unused |
|---|---|---|---|
| 0A:012 | 「むみょうしょうにん」は すごい盾を もっているらしいのだが だれにも ゆずらないそうだ。 | They say "Saint Mumyo" has an amazing shield, but he won't give it to anyone. | Its person (C6) has a record but is not on Island Town's map. |
| 0A:013 | あっ! あなたが 盾を ゆずってもらったんですね。 | Oh! So he gave you the shield. | Same person (C6). |
| 0A:014 | ね、ね! きいて! このうちにね、ひどいケガ人がいるの! かわった かっこうをした人 なのよ。 | Hey, hey! Listen! Someone in this house is badly hurt! She's dressed really strangely! | No person record points here. Person C7 points to 0A:018, the same line as person C9, so C7 was probably this girl and was redirected. |
| 0A:015 | ケガ人のなまえね、美剣っていうの! | Her name is Mitsurugi! | Same as above. |
| 0A:022 | 朱紗くん...きをつけて... 凄ノ王は..すごいESPを... つかうの... | Susa... be careful... Susano Oh... uses powerful ESP... | No record. This is the injured Mitsurugi herself. |
| 0A:023 | ... | ... | No record. Probably her second line, before or after she recovers. |

So a whole small event was cut. In it, Mitsurugi lay wounded in a house in Island Town, a girl told you about her, and she warned Susa about Susano Oh's ESP.

## Mountain Village (block 0C)

| Line | Japanese | English | Why it's unused |
|---|---|---|---|
| 0C:022 | ああ...のどが かわいたわ... くるしいの...たすけてください! | Ahh... I'm so thirsty... It's agony... Please help me! | No person record. It fits the village's water crisis. |
| 0C:023 | ここの やどやに ミルツギ12シンとかの ユウレイが でるんですって! それでね へんな話なんだけど 瓜生とかいう人を なざしで さがしているんですってよ。 | They say a ghost of one of Mitsurugi's Twelve Heavenly Generals or something appears at the inn here! And here's the weird part: they say it's searching for someone called Uryuu by name. | No person record. The Japanese misspells the name as ミルツギ, which suggests the line was never proofread. It hints at a cut ghost-at-the-inn event. |

## Night-time houses (block 1B)

| Line | English | Why it's unused |
|---|---|---|
| 1B:006 | What is it? At this hour? Could you come back in the morning? (woman) | No script prints it. The house messages that are used (1B:000-005) come from events 00, 01, 09 and 11. Events 02-08 are empty scripts, so these were probably meant for them. |
| 1B:007 | What is it? At this time of night?! Can't it wait till morning?! (old man) | Same. |
| 1B:008 | It's late at night. Better not go in. | Same. |

## Story blocks

| Line | English | Note |
|---|---|---|
| 1C:053 | What do you want? | Skipped between used lines 1C:052 and 1C:054. |
| 1E:000 | It's late. Could you come back tomorrow? | Near-duplicate of the used line 1E:001. |
| 1F:083 | Ah, big bro, that's MY treasure! No muscling in, got it? | The bandit-brothers scene prints 081, 082, 084, 085 and skips this one. |
| 20:032 | Hey! You don't have enough money. I can't take you up for that, no way. | The airplane script prints 028-031 and 033. The money check was dropped. |
| 20:102 | I'm up above! Hurry, hurry! You can hear Yamata-no-Orochi's voice, can't you?! | Final tower. Lines 098-101 and 104 onward are used. |
| 20:103 | You'd best come quickly! I am on this floor! | Same. |

**Confidence:** Island Town, Mountain Village and block 1B are certain. For the story blocks, scenes that don't name their block use the current chapter's block, and each scene's chapter is inferred from its neighbours. Those six lines are therefore very likely unused, but not proven.
