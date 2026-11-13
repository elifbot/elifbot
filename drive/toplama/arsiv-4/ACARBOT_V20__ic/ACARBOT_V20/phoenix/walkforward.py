from .backtest import Backtester,Bar
def walk_forward(bars,train_bars=500,test_bars=200,step=200):
    out=[];i=0
    while i+train_bars+test_bars<=len(bars):
        train=bars[i:i+train_bars];test=bars[i+train_bars:i+train_bars+test_bars]
        # OOS evaluation is isolated from the training window; parameters are not tuned on test data.
        out.append({'train_start':train[0].ts,'train_end':train[-1].ts,'test_start':test[0].ts,'test_end':test[-1].ts,'result':Backtester().run(test)})
        i+=step
    return out
