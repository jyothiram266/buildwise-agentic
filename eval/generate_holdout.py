"""A held-out intent set, written to be hard for the keyword scorer.

Why this file exists: `intents.jsonl` scores 100% with the offline provider, and
that number is worthless as an accuracy claim, because the keyword lists in
`llm/mock_provider.py` were tuned against it. Fitting a rule engine to its own test
set is trivial and proves nothing.

These messages are written to avoid the tuned vocabulary on purpose:

* indirect phrasing that names no keyword ("the wall is going dark near the window")
* colloquial and code-switched English of the kind Indian customers actually send
* misspellings and SMS compression
* the same underlying intent expressed through a different frame ("do I still owe
  you anything" instead of "what are my dues")

The gap between `intent` and `intent_holdout` in the report is the interesting
number. A large gap means the scorer memorised phrasings rather than learning the
distinction — which is exactly what a keyword scorer does, and exactly why a real
model belongs in this slot for production.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "datasets" / "intents_holdout.jsonl"

HOLDOUT: list[tuple[str, str]] = [
    # SALES_INQUIRY — indirect, colloquial, no template vocabulary
    ("hi, saw ur ad. wat r d rates in whitefield side", "SALES_INQUIRY"),
    ("me and my wife are house hunting, something around 90L, 2 bedrooms", "SALES_INQUIRY"),
    ("is aurora heights worth seeing this sunday", "SALES_INQUIRY"),
    ("kitna aayega for a three bedroom in gachibowli", "SALES_INQUIRY"),
    ("we need something bigger, currently in a rented 1bhk", "SALES_INQUIRY"),
    ("send details na", "SALES_INQUIRY"),
    ("what all is there in the complex, gym pool etc", "SALES_INQUIRY"),
    ("my budget is tight, whats the cheapest you have in pune", "SALES_INQUIRY"),
    # BOOKING
    ("i gave the token last tuesday, whats happening now", "BOOKING"),
    ("can u block 1204 for me till friday", "BOOKING"),
    ("i want to move to my wifes name instead", "BOOKING"),
    ("if i back out now do i lose the token", "BOOKING"),
    # DOCUMENTATION
    ("what all papers do i need to bring on registration day", "DOCUMENTATION"),
    ("i sent my aadhar last week did u get it", "DOCUMENTATION"),
    ("the bank letter is old now, do i need a fresh one", "DOCUMENTATION"),
    ("my father is joint owner, does he also need to sign", "DOCUMENTATION"),
    ("still anything left from my side before handover", "DOCUMENTATION"),
    # PAYMENT
    ("do i still owe you anything", "PAYMENT"),
    ("got a letter asking for 8 lakhs, i thought i cleared that", "PAYMENT"),
    ("when is the next amount coming up", "PAYMENT"),
    ("bank released the money on monday, has it come to you", "PAYMENT"),
    ("are you charging me extra for the late one", "PAYMENT"),
    # CONSTRUCTION_STATUS
    ("how much is done on my building", "CONSTRUCTION_STATUS"),
    ("when can we shift in", "CONSTRUCTION_STATUS"),
    ("is the plastering over on my floor", "CONSTRUCTION_STATUS"),
    ("drove past yesterday, looked like nothing moved in months", "CONSTRUCTION_STATUS"),
    ("any idea when keys will be given", "CONSTRUCTION_STATUS"),
    # MAINTENANCE
    ("the wall is going dark near the window after the rain", "MAINTENANCE"),
    ("geyser giving cold water only", "MAINTENANCE"),
    ("something smells bad in the bathroom, i think its the drain", "MAINTENANCE"),
    ("ac point in the hall has no current", "MAINTENANCE"),
    ("watchman says the camera at gate 2 is off", "MAINTENANCE"),
    ("bathroom tap wont stop", "MAINTENANCE"),
    ("there is a big sound from the shaft whenever anyone goes up", "MAINTENANCE"),
    ("my balcony floor is coming up in one corner", "MAINTENANCE"),
    ("no one has cleaned our passage this week", "MAINTENANCE"),
    # CONTRACTOR_UPDATE
    ("boss, 30 bags left only, tomorrow we sit idle", "CONTRACTOR_UPDATE"),
    ("shuttering party did not come today, only 8 men on site", "CONTRACTOR_UPDATE"),
    ("we poured yesterday night, will strip after 3 days", "CONTRACTOR_UPDATE"),
    ("machine is down, mechanic coming tomorrow", "CONTRACTOR_UPDATE"),
    ("sir our last two bills not cleared, labour is asking", "CONTRACTOR_UPDATE"),
    ("heavy rain from morning, nothing can be done", "CONTRACTOR_UPDATE"),
    ("finishing needs 2 more weeks than what we agreed", "CONTRACTOR_UPDATE"),
    # COMPLAINT_ESCALATION
    ("i am done being polite about this", "COMPLAINT_ESCALATION"),
    ("this is the last time i am writing before i take other steps", "COMPLAINT_ESCALATION"),
    ("we will see you in court", "COMPLAINT_ESCALATION"),
    ("give my money back, i dont want the flat", "COMPLAINT_ESCALATION"),
    ("i am putting all of this on twitter tonight", "COMPLAINT_ESCALATION"),
    ("four emails and not one reply, is anyone even there", "COMPLAINT_ESCALATION"),
    ("you people have been lying about the date from day one", "COMPLAINT_ESCALATION"),
    ("i will approach the authority if this is not sorted", "COMPLAINT_ESCALATION"),
    # OTHER
    ("ok noted", "OTHER"),
    ("who do i talk to about the club membership form", "OTHER"),
    ("are you people working tomorrow, its a holiday na", "OTHER"),
    ("pls note my new number", "OTHER"),
    ("thanks a lot for yesterday", "OTHER"),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as handle:
        for text, intent in HOLDOUT:
            handle.write(json.dumps({"text": text, "intent": intent}) + "\n")
    print(f"  {OUT.name}: {len(HOLDOUT)} rows")


if __name__ == "__main__":
    main()
