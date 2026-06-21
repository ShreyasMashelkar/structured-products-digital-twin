import os
import pandas as pd
from typing import Dict, Any, List

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
PORTFOLIO_FILE = os.path.join(DATA_DIR, 'portfolio.csv')
COUNTERPARTIES_FILE = os.path.join(DATA_DIR, 'counterparties.csv')
CSA_FILE = os.path.join(DATA_DIR, 'csa_master.csv')


class PortfolioManager:
    """Manages reading and writing to the portfolio CSV files."""
    
    @staticmethod
    def load_portfolio() -> pd.DataFrame:
        """Load the trades portfolio."""
        if not os.path.exists(PORTFOLIO_FILE):
            return pd.DataFrame(columns=['TradeID', 'TradeType', 'Counterparty', 
                                         'Notional', 'StartDate', 'Maturity', 
                                         'FixedRate', 'Direction', 'CSA_ID'])
        return pd.read_csv(PORTFOLIO_FILE)

    @staticmethod
    def save_portfolio(df: pd.DataFrame):
        """Save the trades portfolio."""
        df.to_csv(PORTFOLIO_FILE, index=False)

    @staticmethod
    def load_counterparties() -> pd.DataFrame:
        """Load the counterparties database."""
        if not os.path.exists(COUNTERPARTIES_FILE):
            return pd.DataFrame(columns=['Counterparty', 'Sector', 'Rating', 
                                         'RecoveryRate', 'FundingSpread', 'RiskWeight'])
        return pd.read_csv(COUNTERPARTIES_FILE)

    @staticmethod
    def load_csas() -> pd.DataFrame:
        """Load the CSA master database."""
        if not os.path.exists(CSA_FILE):
            return pd.DataFrame(columns=['CSA_ID', 'Counterparty', 'Threshold', 'MTA', 'MPOR_Days'])
        return pd.read_csv(CSA_FILE)
        
    @staticmethod
    def add_trade(trade: Dict[str, Any]):
        """Add a single trade to the portfolio."""
        df = PortfolioManager.load_portfolio()
        # Generate new TradeID
        if df.empty:
            new_id = 1
        else:
            new_id = int(df['TradeID'].max()) + 1
            
        trade['TradeID'] = new_id
        
        # Validate required fields
        required = ['TradeType', 'Counterparty', 'Notional', 'StartDate', 
                    'Maturity', 'FixedRate', 'Direction', 'CSA_ID']
        for req in required:
            if req not in trade:
                raise ValueError(f"Missing required field: {req}")
                
        new_row = pd.DataFrame([trade])
        df = pd.concat([df, new_row], ignore_index=True)
        PortfolioManager.save_portfolio(df)
        return new_id

    @staticmethod
    def delete_trade(trade_id: int):
        """Delete a trade by ID."""
        df = PortfolioManager.load_portfolio()
        df = df[df['TradeID'] != trade_id]
        PortfolioManager.save_portfolio(df)

    @staticmethod
    def get_csa_for_trade(csa_id: str) -> Dict[str, Any]:
        """Fetch CSA details by CSA_ID."""
        csas = PortfolioManager.load_csas()
        match = csas[csas['CSA_ID'] == csa_id]
        if match.empty:
            return {}
        return match.iloc[0].to_dict()
        
    @staticmethod
    def get_counterparty(name: str) -> Dict[str, Any]:
        """Fetch Counterparty details."""
        cptys = PortfolioManager.load_counterparties()
        match = cptys[cptys['Counterparty'] == name]
        if match.empty:
            return {}
        return match.iloc[0].to_dict()
