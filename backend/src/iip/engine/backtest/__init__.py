"""Pure backtest engine (research-backtest-method.md §6-§7).

Modules: ``ledger`` (cash, FIFO lots, realisations, terminal liquidation), ``costs_equity`` (point-in-time equity and
ETF trading costs, fixture C-1), ``tax_lots`` (per-year capital-gains tax on realised lots, fixture T-1). No clock, IO
or randomness; Decimal for every ₹ amount.
"""
