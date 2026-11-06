# Manual Grocery Scraper Instructions

This is a modified version of the grocery scraper that provides more control and better handling of DataDome challenges.

## Usage

### Prerequisites
- Python 3.8+
- SeleniumBase installed (`pip install seleniumbase`)

### Running the Script

1. **First run (manual CAPTCHA)**:
   ```bash
   python food_bank_builder_manual.py --store "Food Lion" --search bread --headed
   ```
   Complete the DataDome CAPTCHA manually when prompted.

2. **Subsequent runs (using saved session)**:
   ```bash
   python food_bank_builder_manual.py --store "Food Lion" --search bread --headless
   ```

## Key Features

- More detailed logging to help understand what's happening at each step
- Improved DataDome challenge detection and handling
- Better error messages for troubleshooting
- Clear indication of when CAPTCHA needs to be completed manually
- Extended timeouts for page loading and CAPTCHA completion

## Important Notes

- The script uses a dedicated `.chrome-profile` directory to remember sessions between runs
- DataDome requires manual CAPTCHA completion on first access
- After completing one CAPTCHA manually, subsequent runs can be headless
- Don't run two searches simultaneously as they share the same profile
- The script will wait for CAPTCHA completion with clear instructions

## Troubleshooting

### If you get a "DataDome blocked" error:
1. This means your IP has been temporarily blocked by DataDome
2. Wait a few hours or try from a different network
3. Try running with `--headed` mode to complete CAPTCHA manually

### If the script seems to lock up:
1. This may be due to DataDome waiting for interaction
2. Check that you've completed any manual CAPTCHAs
3. The script will wait up to 120 seconds for CAPTCHA completion

## Manual Interaction Required

The following steps require manual interaction:
1. First run with `--headed` mode (to complete initial CAPTCHA)
2. Any time DataDome presents a CAPTCHA challenge (this is expected behavior)

The script handles the session persistence automatically through the `.chrome-profile` directory, so after the first manual completion, all subsequent runs can be headless.