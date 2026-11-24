# Tiny test KGs

Two very small knowledge graphs, each a TBox + ABox pair, for trying the whole flow quickly
(test data only; the app never loads them by itself).

| KG | fact class | measures | dimensions | facts |
|---|---|---|---|---|
| `shop` | Sale | quantity, amount | Customer → City, Product → Category | 6 |
| `bank` | Transfer | transferAmount, fee | Client, Branch → City | 4 |

The KGs share one person under different IRIs: `shop:alice` and `bank:client_17` are both
"Alice Rahman" with the same email, so Build should link them (`owl:sameAs`). It also links the
two Dhaka cities (`shop:dhaka`, `bank:dhaka`); Chittagong / Chattogram stay apart (different spelling).

Hand-computed answers:

- shop amount by category: Electronics 3,780.00 · Books 45.00 (total 3,825.00)
- bank transferAmount by branch: Gulshan 5,000.00 · Agrabad 325.00
- Alice across both KGs: shop amount 1,630.00 · bank transferAmount 1,250.00

Try it:

```bash
cd backend && uv run kg2analyzer build tests/fixtures/tiny --out /tmp/tiny-mdkg
```

## Example questions for Ask

All of these run with the LLM switched off (grounded parser + embeddings) in 20 to 60 ms.

| Question | Expected answer | How it is understood |
|---|---|---|
| Total amount by category in shop | Electronics 3,780.00 · Books 45.00 | exact words |
| Total quantity sold for Electronics | 5 | member filter |
| Average amount per customer in shop | Carol Das 980.00 · Bob Hossain 607.50 · Alice Rahman 543.33 | AVG |
| Total shop amount by city | Dhaka 2,610.00 · Chittagong 1,215.00 | roll-up Customer → City |
| Total shop amount for Alice Rahman | 1,630.00 | member filter |
| Total transfer amount by branch | Gulshan 5,000.00 · Agrabad 325.00 | exact words |
| Total transfer amount by city in bank | Dhaka 5,000.00 · Chattogram 325.00 | roll-up Branch → City |
| Total fees per branch in the bank | Gulshan 15.00 · Agrabad 3.50 | exact words |
| Total transfers for Alice Rahman | 1,250.00 | member filter |
| How much money was sent through each branch? | Gulshan 5,000.00 · Agrabad 325.00 | embedding: "money was sent" ≈ transfer amount |
| What are the total charges by bank branch? | Gulshan 15.00 · Agrabad 3.50 | embedding: "charges" ≈ fee |
| Total transfer amount by town | Dhaka 5,000.00 · Chattogram 325.00 | embedding: "town" ≈ city |
| Total amount by catagory | Electronics 3,780.00 · Books 45.00 | spelling: "catagory" ≈ category |
| Total shop amount and bank transfer amount for shared customers | Alice: 1,630.00 (shop) · 1,250.00 (bank) | cross-KG join through owl:sameAs |
| Show total sales and money sent for customers who are in both | Alice: 1,630.00 · 1,250.00 | join + embedding |
| Delete all sales in the shop | rejected | read-only |
| What is the weather in Dhaka? | rejected | out of scope |

