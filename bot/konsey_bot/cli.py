import argparse
from bot.konsey_bot.ayarlar import Ayarlar
from bot.konsey_bot.strateji import EMA
from bot.konsey_bot.motor import Motor

def main():
    parser = argparse.ArgumentParser(description='Paper Trading Bot')
    parser.add_argument('--dakika', type=float, default=5, help='Time interval in minutes')
    parser.add_argument('--sembol', type=int, default=5, help='Number of symbols to trade')
    parser.add_argument('--etiket', type=str, default='paper', help='Trade label')

    args = parser.parse_args()

    # Initialize motor with settings
    motor = Motor(Ayarlar.notional_usd, Ayarlar.stop_yuzde)

    # Generate synthetic price
    synthetic_price = EMA.generate_synthetic_price()

    # Run the motor
    motor.tick(synthetic_price, args.dakika, args.sembol)

    # Get and print the summary
    summary = motor.ozet()
    print(summary)

if __name__ == '__main__':
    main()
