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
