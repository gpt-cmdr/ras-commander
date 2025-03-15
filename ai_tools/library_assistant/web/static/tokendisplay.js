/******************************************
 * tokenDisplay.js (type="text/babel")
 * 
 * Enhanced React components for token display:
 *   - TokenDisplay: Main component for showing token usage
 *   - ProgressBar: Visual indicator of token usage
 *   - TokenBreakdown: Detailed token count display
 *   - CostBreakdown: Cost estimation display
 * 
 * Features:
 *   - Real-time token calculation
 *   - Color-coded warnings
 *   - Detailed cost breakdown
 *   - Progress visualization
 *   - Error handling
 ******************************************/

// Utility functions
const formatNumber = (num) => (num ? num.toLocaleString() : '0');
const formatCurrency = (amount) => `$${(amount || 0).toFixed(6)}`;
const calculateCostPerMillion = (rate) => (rate).toFixed(2);  // Rate is already per million

// TokenBreakdown component for detailed token counts
const TokenBreakdown = ({ component_tokens = {}, output_length = 0 }) => (
  <div className="token-breakdown">
    <div className="d-flex justify-content-between">
      <span>System Message:</span>
      <span>{formatNumber(component_tokens.system)}</span>
    </div>
    <div className="d-flex justify-content-between">
      <span>Conversation History:</span>
      <span>{formatNumber(component_tokens.history)}</span>
    </div>
    <div className="d-flex justify-content-between">
      <span>Selected Context:</span>
      <span>{formatNumber(component_tokens.rag)}</span>
    </div>
    <div className="d-flex justify-content-between">
      <span>Current Message:</span>
      <span>{formatNumber(component_tokens.user_input)}</span>
    </div>
    <div className="d-flex justify-content-between">
      <span>Expected Output:</span>
      <span>{formatNumber(output_length)}</span>
    </div>
  </div>
);

// Enhanced ProgressBar with color coding
const ProgressBar = ({ usage_ratio = 0, usage_color = 'primary' }) => {
  const progressWidth = `${Math.min(usage_ratio * 100, 100)}%`;
  return (
    <div className="progress mt-2">
      <div 
        className={`progress-bar bg-${usage_color}`}
        role="progressbar"
        style={{ width: progressWidth }}
        aria-valuenow={usage_ratio * 100}
        aria-valuemin="0"
        aria-valuemax="100"
      />
    </div>
  );
};

// CostBreakdown component for detailed cost analysis
const CostBreakdown = ({ 
  total_tokens_used = 0,
  output_length = 0,
  prompt_cost_per_1m = 0,
  completion_cost_per_1m = 0,
  cost_estimate = 0
}) => (
  <div className="cost-breakdown mt-3">
    <div className="d-flex justify-content-between">
      <span>Input Cost:</span>
      <span>
        {formatNumber(total_tokens_used)} × $
        {calculateCostPerMillion(prompt_cost_per_1m)}/1M = 
        {formatCurrency((total_tokens_used / 1000000) * prompt_cost_per_1m)}
      </span>
    </div>
    <div className="d-flex justify-content-between">
      <span>Output Cost:</span>
      <span>
        {formatNumber(output_length)} × $
        {calculateCostPerMillion(completion_cost_per_1m)}/1M = 
        {formatCurrency((output_length / 1000000) * completion_cost_per_1m)}
      </span>
    </div>
    <div className="d-flex justify-content-between fw-bold mt-1">
      <span>Total Cost:</span>
      <span>{formatCurrency(cost_estimate)}</span>
    </div>
  </div>
);

// Create a context for token data
const TokenDataContext = React.createContext({
  tokenData: null,
  updateTokenData: () => {},
  isReady: false
});

// Custom hook for using token data
const useTokenData = () => {
  const context = React.useContext(TokenDataContext);
  if (!context) {
    throw new Error('useTokenData must be used within a TokenDataProvider');
  }
  return context;
};

// Provider component that holds token data state
const TokenDataProvider = ({ children }) => {
  const [tokenData, setTokenData] = React.useState(null);
  const [isReady, setIsReady] = React.useState(false);
  
  // Update function that validates data before setting state
  const updateTokenData = React.useCallback((newData) => {
    console.log('TokenDataProvider.updateTokenData called with:', newData);
    if (newData && typeof newData === 'object') {
      setTokenData(newData);
      
      // Dispatch event for non-React components that need to know about updates
      const event = new CustomEvent('tokenDataUpdated', { detail: newData });
      window.dispatchEvent(event);
    } else {
      console.warn('Invalid token data received:', newData);
    }
  }, []);

  // Set up global access on mount
  React.useEffect(() => {
    console.log('TokenDataProvider mounted, setting up global access');
    
    // Create a stable reference to updateTokenData
    window.updateTokenDisplays = updateTokenData;
    window.isTokenDisplayReady = () => isReady;
    
    // Signal that the provider is ready
    setIsReady(true);
    window.dispatchEvent(new CustomEvent('tokenDisplayReady'));
    
    return () => {
      // Cleanup on unmount
      delete window.updateTokenDisplays;
      delete window.isTokenDisplayReady;
    };
  }, [updateTokenData]);

  const value = React.useMemo(() => ({
    tokenData,
    updateTokenData,
    isReady
  }), [tokenData, updateTokenData, isReady]);

  return (
    <TokenDataContext.Provider value={value}>
      {children}
    </TokenDataContext.Provider>
  );
};

// Update TokenDisplay to use context
const TokenDisplay = () => {
  const { tokenData } = useTokenData();

  // Loading state
  if (!tokenData) {
    return (
      <div className="text-muted p-3 text-center">
        <div className="spinner-border spinner-border-sm me-2" role="status">
          <span className="visually-hidden">Loading...</span>
        </div>
        Calculating token usage...
      </div>
    );
  }

  // Error state
  if (tokenData.error) {
    return (
      <div className="alert alert-danger m-3">
        <strong>Error:</strong> {tokenData.error}
      </div>
    );
  }

  const {
    component_tokens,
    total_tokens_with_output,
    max_tokens,
    usage_ratio,
    usage_color,
    prompt_cost_per_1m,
    completion_cost_per_1m,
    total_tokens_used,
    output_length,
    cost_estimate
  } = tokenData;

  return (
    <div className="token-usage-container p-3">
      <TokenBreakdown 
        component_tokens={component_tokens} 
        output_length={output_length} 
      />
      
      <hr className="my-2"/>
      
      <div className="d-flex justify-content-between fw-bold">
        <span>Total:</span>
        <span>{formatNumber(total_tokens_with_output)}</span>
      </div>

      <ProgressBar 
        usage_ratio={usage_ratio} 
        usage_color={usage_color} 
      />
      
      <small className="text-muted d-block text-end mb-2">
        {formatNumber(total_tokens_with_output)} / {formatNumber(max_tokens)} tokens available
        {usage_ratio > 0.9 && (
          <span className="text-warning ms-2">
            ⚠️ Approaching token limit
          </span>
        )}
      </small>

      <CostBreakdown 
        total_tokens_used={total_tokens_used}
        output_length={output_length}
        prompt_cost_per_1m={prompt_cost_per_1m}
        completion_cost_per_1m={completion_cost_per_1m}
        cost_estimate={cost_estimate}
      />
    </div>
  );
};

// Simplified TokenDisplayManager that uses the provider
class TokenDisplayManager extends React.Component {
  render() {
    return (
      <TokenDataProvider>
        <TokenDisplay />
      </TokenDataProvider>
    );
  }
}

// Initialize when the DOM is ready
const initializeTokenDisplay = () => {
  const container = document.getElementById('token-usage-details');
  if (!container) {
    console.error('Token display container not found');
    return;
  }

  try {
    console.log('Initializing token display component...');
    const root = ReactDOM.createRoot(container);
    root.render(<TokenDisplayManager />);
    console.log('Token display component rendered');
  } catch (error) {
    console.error('Error initializing token display:', error);
    container.innerHTML = `
      <div class="alert alert-danger m-3">
        Failed to initialize token display: ${error.message}
      </div>
    `;
  }
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initializeTokenDisplay);
} else {
  initializeTokenDisplay();
}
