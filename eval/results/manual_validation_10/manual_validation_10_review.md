# Manual Retrieval Validation

I selected 10 short English questions with answers that could be verified directly from `combined.csv`. I then used the same questions to test the existing Sanskrit-only, English-only, and Sanskrit–English retrieval indexes.

For each question, I reviewed the first retrieved passage and rated it as:

- **Correct:** directly answered the question
- **Partially Correct:** relevant, but did not give the complete answer
- **Wrong:** did not answer the question

During verification, I found that two questions had incorrect reference-row numbers. I corrected these rows using `combined.csv` and confirmed that the other eight references were accurate. This correction did not change any retrieved results.

## Results


| Retrieval system   | Correct | Partially Correct | Wrong |
| ------------------ | ------- | ----------------- | ----- |
| Sanskrit-only      | 0       | 3                 | 7     |
| English-only       | 5       | 4                 | 1     |
| Sanskrit + English | 6       | 3                 | 1     |


In this small review, the English-only and Sanskrit–English indexes returned more useful first results than the Sanskrit-only index. The combined index had one more fully correct result than the English-only index. However, because this evaluation contains only 10 questions, I am using it as a manual comparison rather than a final performance conclusion.

---



## mv10_01

QUESTION: Which sage did Valmiki ask about a man of outstanding virtue?

EXPECTED ANSWER: Narada

GOLD VERSE: row 0 | ramayana chapter 1 shloka 1

The ascetic Vālmīki asked Nārada, the best of sages and foremost of those conversant with words, ever engaged in austerities and Vedic studies.

SANSKRIT-ONLY:
Top 1 retrieved English translation: You are highly intelligent, O Yudhishthira! It is what you say. The person is very rare who is endued with all those good qualities.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: O foremost of men, do you ask particularly, about this, Vālmīki, the foremost of ascetics. They being all thus struck with curiosity, Satrughna said: It is not proper for us, O You soldiers, to question him in this way. There are many such wonders in the hermitage of this ascetic.
Gold rank: 2

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: The ascetic Vālmīki asked Nārada, the best of sages and foremost of those conversant with words, ever engaged in austerities and Vedic studies.
Gold rank: 1

MY MANUAL VERDICT:
Sanskrit: **Wrong** 

English: Partially Correct

Sanskrit + English: 

Correct Notes: Sanskrit is unrelated. English mentions Valmiki and asking but does not identify Narada. Combined directly states that Valmiki asked Narada.

---



## mv10_02

QUESTION: After meeting the Nishada king Guha, where did Rama dismiss his charioteer?

EXPECTED ANSWER: On the banks of the Ganges at Srigaverapura

GOLD VERSE: row 24 | ramayana chapter 1 shloka 25

Rāma met with the virtuous and beloved king of the Nişādas; and then in company with Guha, Laksmana, and Sita, Rama dismissed his charioteer on the banks of the Ganges at Srigaverapura.

SANSKRIT-ONLY:
Top 1 retrieved English translation: There lived at the place a king named Guha, a friend to Răma, dear as his own self, a Nişāda by birth, powerful and famed as the lord of the Nişādas.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: Rāma met with the virtuous and beloved king of the Nişādas; and then in company with Guha, Laksmana, and Sita, Rama dismissed his charioteer on the banks of the Ganges at Srigaverapura.
Gold rank: 1

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Rāma met with the virtuous and beloved king of the Nişādas; and then in company with Guha, Laksmana, and Sita, Rama dismissed his charioteer on the banks of the Ganges at Srigaverapura.
Gold rank: 1

MY MANUAL VERDICT: Sanskrit: Partially Correct 

English: Correct 

Sanskrit + English: Correct

Notes: Sanskrit retrieves the correct Guha episode but does not give the requested location. English and combined directly provide the full location.

---



## mv10_03

QUESTION: When Kaikeyi claimed the two boons she had been promised, what two things did she ask for?

EXPECTED ANSWER: The exile of Rama and the installation of Bharata

GOLD VERSE: row 19 | ramayana chapter 1 shloka 20

Beholding the provisions of the installation, that lady the king's consort, Kaikeyī, who had previously been promised two boons, even asked him for those viz., the exile of Ráma, and the installation of Bharata.

SANSKRIT-ONLY:
Top 1 retrieved English translation: This very subject which you have introduced regarding the merits of the gift of flowers and incense and lamps, came up on the occasion. Indeed the king of the Daityas put this high question of Shukra that most learned of all ascetics.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: Beholding the provisions of the installation, that lady the king's consort, Kaikeyī, who had previously been promised two boons, even asked him for those viz., the exile of Ráma, and the installation of Bharata.
Gold rank: 1

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Beholding the provisions of the installation, that lady the king's consort, Kaikeyī, who had previously been promised two boons, even asked him for those viz., the exile of Ráma, and the installation of Bharata.
Gold rank: 1

MY MANUAL VERDICT: Sanskrit: Wrong 

English: Correct 

Sanskrit + English: Correct 

Notes: Sanskrit is unrelated. English and combined retrieve the corrected gold verse at rank 1 and explicitly state both requests.

---



## mv10_04

QUESTION: Why did king Dasaratha banish his son Rama?

EXPECTED ANSWER: Because he was bound by duty to keep his promise

GOLD VERSE: row 20 | ramayana chapter 1 shloka 21

Bound by the ties of duty in consequence of his promise, king Dasaratha banished his favourite son Rāma.

SANSKRIT-ONLY:
Top 1 retrieved English translation: Our father the king Daśaratha was entirely under the control of passions, and hence for the satisfaction of Kaikeyi did not install Rāma.-
Gold rank: 5

ENGLISH-ONLY:
Top 1 retrieved English translation: Bound by the ties of duty in consequence of his promise, king Dasaratha banished his favourite son Rāma.
Gold rank: 1

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Bound by the ties of duty in consequence of his promise, king Dasaratha banished his favourite son Rāma.
Gold rank: 1

MY MANUAL VERDICT: Sanskrit: Partially Correct 

English: Correct 

Sanskrit + English: Correct 

Notes: Sanskrit gives the related reason of satisfying Kaikeyi but does not clearly mention the binding promise. English and combined directly state the expected reason.

---



## mv10_05

QUESTION: After Dasaratha died, did Bharata accept the throne when Vasistha and the other Brahmanas pressed him to rule?

EXPECTED ANSWER: No. He refused the kingdom and went to the forest to seek Rama.

GOLD VERSE: row 27 | ramayana chapter 1 shloka 28

When king Dasaratha had passed away heaven, the mighty Bharata, although pressed by the Brāhmaṇas headed by Vasiştha, to rule the kingdom, did not wish for dominion. And that hero went the forest, with the view of propitiating Rāma.

SANSKRIT-ONLY:
Top 1 retrieved English translation: You should give instead of refusing, O chief of Bharata's race!' Bibhatsu who was saying so was applauded by king Yudhishthira the just.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: When king Dasaratha had passed away heaven, the mighty Bharata, although pressed by the Brāhmaṇas headed by Vasiştha, to rule the kingdom, did not wish for dominion. And that hero went the forest, with the view of propitiating Rāma.
Gold rank: 1

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: When king Dasaratha had passed away heaven, the mighty Bharata, although pressed by the Brāhmaṇas headed by Vasiştha, to rule the kingdom, did not wish for dominion. And that hero went the forest, with the view of propitiating Rāma.
Gold rank: 1

MY MANUAL VERDICT: 

Sanskrit: Wrong

English: Correct 

Sanskrit + English: Correct

Correct Notes: Sanskrit is unrelated. English and combined clearly state that Bharata refused the kingdom and went to the forest to seek Rama.

---



## mv10_06

QUESTION: When the Ocean appeared and advised them, who built the causeway across the sea?

EXPECTED ANSWER: Nala

GOLD VERSE: row 64 | ramayana chapter 1 shloka 65

Then that lord of rivers, the Ocean, showed himself. And agreeably to the advice of the Ocean, Nala constructed a bridge (over the water.)

SANSKRIT-ONLY:
Top 1 retrieved English translation: All these scattered and shot innumerable arrows at Arjuna in the battle, even as the masses of clouds suddenly pour forth showers of rain, that approach towards the vast ocean.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: Then that lord of rivers, the Ocean, showed himself. And agreeably to the advice of the Ocean, Nala constructed a bridge (over the water.)
Gold rank: 1

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Then that lord of rivers, the Ocean, showed himself. And agreeably to the advice of the Ocean, Nala constructed a bridge (over the water.)
Gold rank: 1

MY MANUAL VERDICT: Sanskrit: wrong

English: Correct 

Sanskrit + English: Correct 

Notes: Sanskrit retrieves an unrelated passage about Arjuna and the ocean. English and combined explicitly name Nala as the builder.

---



## mv10_07

QUESTION: Who lured Rama far from the ashram by taking the form of a golden deer?

EXPECTED ANSWER: Marica

GOLD VERSE: row 6935 | ramayana chapter 57 shloka 6

Surely, the Rākṣasas in a body are desirous of slaying Sitä. Becoming a golden deer, Mārica, having allured me far, transformed himself into a Rākşasa, as soon as he had been struck with my shafts; and exclaimed, 'Ah! Laksmana, slain am I.'

SANSKRIT-ONLY:
Top 1 retrieved English translation: Thus, O son of Kuru's race, did Vasishtha recite formerly this topic to Rama of Bhrigu's race. Do you, therefore, O king of men, try to make gifts of gold.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: (There at) the ten-headed one replied to him "go and tempt Sita wearing the form of a deer with golden horns and a golden skin. It is certain that on beholding you she will send Rama after you".
Gold rank: not in Top 10

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: (There at) the ten-headed one replied to him "go and tempt Sita wearing the form of a deer with golden horns and a golden skin. It is certain that on beholding you she will send Rama after you".
Gold rank: not in Top 10

MY MANUAL VERDICT: 

Sanskrit: Wrong

English: Partially Correct 

Sanskrit + English: Partially Correct 

Notes: English and combined retrieve the correct golden-deer episode, but the Top-1 verse refers to Marica only as “him” and does not identify him by name.

---



---



## mv10_08

QUESTION: What did Ekalavya cut off and give to Drona as the teacher's fee?

EXPECTED ANSWER: His right thumb

GOLD VERSE: row 23857 | mahabharata chapter 132 shloka 50

Ekalavya ever devoted to truth and desirous of keeping his promise, hearing the fearful words of Drona, at once cut off his right thumb with a cheerful face and unruffled heart and gave it to Drona.

SANSKRIT-ONLY:
Top 1 retrieved English translation: O king, thereupon Drona spoke thus to Ekalavya, "O hero, if you are really my pupil, give me my remuneration. Ekalavya was much pleased in hearing this and he said-
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: O king, thereupon Drona spoke thus to Ekalavya, "O hero, if you are really my pupil, give me my remuneration. Ekalavya was much pleased in hearing this and he said-
Gold rank: 5

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: O king, thereupon Drona spoke thus to Ekalavya, "O hero, if you are really my pupil, give me my remuneration. Ekalavya was much pleased in hearing this and he said-
Gold rank: 2

MY MANUAL VERDICT:
Sanskrit: Partially Correct
English: Partially Correct
Sanskrit + English: Partially Correct
Notes: All three Top-1 results retrieve the immediately related verse where Drona asks Ekalavya for payment, but they do not state that Ekalavya gave his right thumb. The direct gold verse appears at rank 5 for English and rank 2 for combined.

---



## mv10_09

QUESTION: How far did Hanuman say he leaped across the ocean to carry out Rama's work?

EXPECTED ANSWER: One hundred yojanas

GOLD VERSE: row 33766 | mahabharata chapter 148 shloka 6

Thereupon to accomplish the work of Rama of stainless deeds, I suddenly leaped over the ocean extending one hundred yojanas.

SANSKRIT-ONLY:
Top 1 retrieved English translation: This measureless deep was dug out by (the king) Sagara.* And the great ocean shall surely help Rāma belonging to Sagara's race. *Sagara was a sovereign of Ayodhyā, belonging to the same family with Rāma.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: Hanuman said: Who is he of the name of Hanuman who leaped over the ocean. O foremost of men I ask you, relate it if you can.
Gold rank: 2

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Hanuman said: Who is he of the name of Hanuman who leaped over the ocean. O foremost of men I ask you, relate it if you can.
Gold rank: 2

MY MANUAL VERDICT:  
Sanskrit: Wrong  
English: Partially Correct  
Sanskrit + English: Partially Correct  
Notes: Sanskrit does not answer the question. English and combined identify Hanuman’s ocean leap but do not provide the distance of one hundred yojanas. The exact gold verse appears at rank 2.

## mv10_10

QUESTION: In Krishna's teaching to Arjuna, what does he say a person should be concerned with, and never with?

EXPECTED ANSWER: Concerned only with actions, never with their fruits

GOLD VERSE: row 48027 | mahabharata chapter 26 shloka 46

Your concern is only with actions, never with their fruits. Let not the fruits of actions be your motive. (at the same time) let not your inclination be towards action.

SANSKRIT-ONLY:
Top 1 retrieved English translation: Arjuna said : O Gandharva, if you give me out of your satisfaction for obtaining life in a crisis, these horses and the wealth of science shall not accept it.
Gold rank: not in Top 10

ENGLISH-ONLY:
Top 1 retrieved English translation: Arjuna said What is the end of him, O Krishna who has not earned success in devotion, being not assiduous, and having a mind shaken off from devotion, through full of faith?
Gold rank: not in Top 10

SANSKRIT + ENGLISH:
Top 1 retrieved English translation: Arjuna said What is the end of him, O Krishna who has not earned success in devotion, being not assiduous, and having a mind shaken off from devotion, through full of faith?
Gold rank: not in Top 10

MY MANUAL VERDICT:  
Sanskrit: Wrong  
English: Wrong  
Sanskrit + English: Wrong  
Notes: Sanskrit is unrelated. English and combined retrieve a different teaching about failure in devotion. None of the Top-1 passages answer the question about actions and their fruits.