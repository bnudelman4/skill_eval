"""Deterministic cross-checks on a ledger that don't require external gold.

The verify pipeline triangulates against an independent gold source (SEC,
Daloopa). These checks are complementary: they verify the LLM transcribed and
computed correctly from the *candidate* source (FMP) it was given. Together,
they split failure attribution cleanly:

    FMP-self-check  FAIL  +  SEC anchor PASS   → LLM error (skill wrong)
    FMP-self-check  PASS  +  SEC anchor FAIL   → FMP vs SEC disagreement
    FMP-self-check  FAIL  +  SEC anchor FAIL   → likely LLM error
    FMP-self-check  PASS  +  SEC anchor PASS   → solid
"""
