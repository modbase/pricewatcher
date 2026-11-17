# Glossary

**Product**
The thing the user wants to buy, independent of any shop. One row in the main overview. Identified by a name plus optional EAN, MPN or ASIN.
_Avoid_: item, watch

**Shop**
A retailer website the user can select per Product (e.g. amazon.nl, coolblue.be, bol.com).

**Listing**
A Product's page at one specific Shop, with its own URL and current price. A Product has at most one Listing per selected Shop.
_Avoid_: watch, link

**Match**
Finding the Listing of a Product at a Shop from a name, product code or ASIN, and the user confirming it is the right one.

**Cheapest Shop**
The Shop whose in-stock, non-stale Listing has the lowest price (including shipping when known) for a Product.

**Stale Listing**
A Listing whose last 3 checks failed (the number is a setting). It shows its last good price but no longer counts toward the Cheapest Shop. One successful check makes it a normal Listing again.

**Target Price**
An optional per-Product price; an alert fires when the Cheapest Shop's price falls below it.

**All-time Low**
The lowest Cheapest Shop price ever recorded for a Product. A new All-time Low triggers an alert, whether or not a Target Price is set, unless Settings turn that alert off or the drop is smaller than the minimum set there.
