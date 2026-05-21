




"""# Updates

### Updates to the current portfolio
"""

while True:
  response = input("Do you want to update the portfolio? (y/n) ").strip().lower()

  if response == "n":
    print("Exiting portfolio update process.")
    break
  elif response == "y":
    # User wants to update, proceed with the rest of the loop
    pass # No explicit action needed here, just let the code flow
  else:
    print("Invalid input. Please enter 'y' for yes or 'n' for no.")
    continue # Go back to the start of the loop

  print("\nCurrent Portfolio Assets:")
  for asset in df["Asset"]:
    print(f"- {asset}")

  # Ask the user to select which asset to update
  asset_name = input("\nWhich asset do you want to update? ").strip()

  # Check if the asset exists in our portfolio
  if asset_name not in df["Asset"].values:
    print(f"The asset '{asset_name}' does not exist in our portfolio.")
    continue

  # Ask for the units and price
  try:
    changed_units = float(input("How many units were bought (2) / sold (-2): "))
    new_purchase_price = float(input("What was the purchase price per unit (EUR): "))

    # Update units and average purchase price
    idx = df[df["Asset"] == asset_name].index[0]
    old_units = df.loc[idx, "Units"]

    # Prevent division by zero or negative units if selling too much
    if old_units + changed_units <= 0 and changed_units < 0:
      print(f"Warning: Cannot sell {abs(changed_units)} units of {asset_name}. You only have {old_units} units. Update cancelled for this asset.")
      continue
    elif old_units + changed_units < 0 and changed_units > 0:
      # This case should not happen if old_units is already positive, but as a safeguard
      print(f"Warning: Invalid unit calculation for {asset_name}. Total units would be negative. Update cancelled.")
      continue

    # Update units
    df.loc[idx, "Units"] = old_units + changed_units

    # Update the average purchasing price only if there are units remaining
    if df.loc[idx, "Units"] > 0:
        df.loc[idx, "Purchase Price"] = ((old_units * df.loc[idx, "Purchase Price"]) + (changed_units * new_purchase_price)) / (old_units + changed_units)
    else:
        # If all units are sold, reset purchase price or handle as desired (e.g., NaN)
        df.loc[idx, "Purchase Price"] = 0.0 # Or np.nan, depending on desired behavior

    # Display the new purchasing price and units to the user
    print(f"New purchasing price: {df.loc[idx, 'Purchase Price']}")
    print(f"New units: {df.loc[idx, 'Units']}")

  except Exception as e:
    print(f"An error occurred: {e}")

"""### Updating if there were new tickers added to Portfolio"""

# Add new assets to the portfolio
import numpy as np # Ensure np is imported if not already in the scope of this cell

while True:
  response = input("Do you want to add new assets to the portfolio? (y/n) ").strip().lower()
  if response == "y":
    try:
      asset_name = input("Asset name:").strip()
      ticker = input("Ticker:").strip()
      currency = input("Currency Yahoo:").strip().upper()
      units = float(input("Units:"))
      purchase_price = float(input("Purchase Price:"))

      # Create a new row
      new_row = {
          "Asset": asset_name,
          "Ticker": ticker,
          "Currency Yahoo": currency,
          "Units": units,
          "Purchase Price": purchase_price,
          "Currency Purchase": "EUR",
          "Price Last Update": np.nan,
          "Date Last Update": np.nan,
          "Value Last Update": np.nan,
          "Profit Last Update": np.nan
      }

      # Append to the dataframe
      global df # Ensure df is modified globally
      df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
      print(f"Asset '{asset_name}' added successfully.")

    except ValueError:
      print("Invalid input for units or purchase price. Please enter numeric values.")
    except Exception as e:
      print(f"An unexpected error occurred: {e}")
  elif response == "n":
    print("Exiting asset addition process.")
    break
  else:
    print("Invalid input. Please enter 'y' for yes or 'n' for no.")

"""Exporting the CSV"""

from datetime import date

# Find the date of today
today = date.today().strftime("%Y-%m-%d")
  get_history,
  _yahoo_session,
  get_prices_batch,
  get_prices_via_chart_api,
  format_new_instrument_assessment,
today

_IDEA_TICKER_ALIASES = {"ORACLE": "ORCL"}
df["Price Last Update"] = df["Price Today (EUR)"]
"""### Investment Possibilities"""
df["Value Last Update"] = df["Price Today (EUR)"] * df["Units"]
new_tickers_input = input("Enter New Ticker symbols (comma-separated), e.g. NVDA, TSLA: ")
raw_symbols = [s.strip().upper() for s in new_tickers_input.replace(";", ",").split(",")]
seen = set()
idea_syms = []
for sym in raw_symbols:
  if not sym:
    continue
  sym = _IDEA_TICKER_ALIASES.get(sym, sym)
  if sym not in seen:
    seen.add(sym)
    idea_syms.append(sym)

if idea_syms:
  sess = _yahoo_session()
  print("\n## Portfolio & New Instruments Analysis")
  for idx, sym in enumerate(idea_syms, start=1):
    ph, info = get_history(sym, session=sess)
    if ph is None or ph.empty or "Close" not in ph.columns:
      print(f"{sym}: Could not load enough history for a live write-up.")
      continue
    print(format_new_instrument_assessment(sym, ph, info, item_index=idx))
    if idx < len(idea_syms):
      print("\n---\n")

  idea_prices = get_prices_batch(idea_syms, session=sess)
  if not idea_prices:
    idea_prices = get_prices_via_chart_api(idea_syms, session=sess)

  print("\n#### Saved ticker ideas")
  print(", ".join(idea_syms))

  print("\n#### Latest prices")
  if idea_prices:
    for sym in idea_syms:
      if sym in idea_prices:
        print(f"- {sym}: {idea_prices[sym]:.2f} (native currency)")
      else:
        print(f"- {sym}: price unavailable")
  else:
    print("Could not load prices right now.")

  print("\n#### Portfolio analysis")
  candidate_kpis = build_portfolio_kpi_dataframe(idea_syms, session=sess)
  display(df_current_portfolio)
  display(candidate_kpis)

  print("\n#### Overall portfolio note")
  try:
    ai_markdown = generate_portfolio_ai_markdown(df_current_portfolio, candidate_kpis)
  except ValueError as exc:
    print(exc)
    ai_markdown = (
      "# Portfolio Analysis (offline)\n\n"
      + format_overall_portfolio_note_heuristic(df_current_portfolio)
    )
  print(ai_markdown)
  display(Markdown(ai_markdown))
else:
  print("No ticker ideas provided. Skipping investment possibilities.")

