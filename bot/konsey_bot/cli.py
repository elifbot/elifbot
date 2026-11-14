import argparse
import json
from bot.konsey_bot.strateji import ema, sinyal
from bot.konsey_bot.risk import boyut, stop_fiyati, pnl
from bot.konsey_bot.motor import Motor



def main():
    parser = argparse.ArgumentParser(description='Konsey Bot CLI')
    parser.add_argument('--dakika', type=float, default=5, help='Dakika aralığı (varsayılan: 5)')
    parser.add_argument('--sembol', type=int, default=5, help='Sembol sayısı (varsayılan: 5)')
    parser.add_argument('--etiket', type=str, default='paper', help='Etiket (varsayılan: paper)')
    args = parser.parse_args()

    motor = Motor()
    motor.tick()

    for _ in range(int(args.dakika * 60 / args.sembol)):
        fiyat = ema() + (random.random() * 2 - 1) * 0.01
        motor.tick(fiyat)
        if motor.pozisyon:
            motor.pozisyon_kapat()
        if sinyal(fiyat):
            motor.pozisyon_ac(fiyat)

    ozet = {
        'kasa': motor.kasa,
        'pnl': pnl(motor.kasa)
    }

    with open(f'runs/{args.etiket}/ozet.json', 'w') as f:
        json.dump(ozet, f)

    print(ozet)


if __name__ == '__main__':
    main()
