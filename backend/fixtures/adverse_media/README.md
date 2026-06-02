# Adverse Media Fixtures

Fixture text blobs used by `AdverseMediaSource` when `CH_USE_FIXTURES=true`.

## Real-retrieval seam

In production, fixture loading is replaced by a call to a news/sanctions API
(e.g. GDELT, Dow Jones Factiva, LexisNexis, OpenSanctions). The swap is clean:

```python
# Current (fixture):
articles = self._load_fixture_articles(entity.registration_number)

# Production (live retrieval):
articles = await self._fetch_from_news_api(entity.name, entity.registration_number)
```

Everything downstream — LLM classification, signal emission, provenance tagging —
is identical on both paths. Only the retrieval step differs.

## Structure

Fixture articles are organised by Companies House registration number so the
source can load the right set per company without any config change:

```
adverse_media/
  {registration_number}/
    article_01_*.txt
    article_02_*.txt
    ...
```

Companies with no subdirectory return zero articles and zero signals — the
source returns `status="ok"` with an empty signal list.

## Test cases encoded in these fixtures

| Company | File | Expected LLM output | Why |
|---|---|---|---|
| SC987654 | `article_01_nca_investigation.txt` | MONEY_LAUNDERING, is_adverse=True, severity=medium | NCA investigation into APP fraud mule accounts — active investigation, named authority |
| SC987654 | `article_02_victim_invoice_fraud.txt` | NOT_ADVERSE, is_adverse=False | Company is the **victim** of invoice fraud, not the perpetrator — rule 3 |
| SC987654 | `article_03_german_decoy.txt` | NOT_ADVERSE, is_adverse=False | Article is about Mule Network Consulting **GmbH** (Frankfurt, HRB 88997) — explicitly a different legal entity — rule 5 |
| 14999001 | `article_01_fca_consumer_warning.txt` | REGULATORY_ACTION, is_adverse=True, severity=high | Formal FCA consumer warning naming the company by number — confirmed regulatory action |

## Hard cases for the LLM

**Victim story (article_02):** The article names the company multiple times and
mentions criminal activity, but the company is clearly described as the target,
not the actor. The prompt explicitly instructs the model to classify NOT_ADVERSE
when the company is the victim. A naive classifier could incorrectly flag this.

**Same-name decoy (article_03):** The article contains serious AML findings but
against a German GmbH with a different registration number, different country,
and an explicit disclaimer of UK connection. The model must notice that the
subject is a different legal entity and not transfer guilt by name association.
