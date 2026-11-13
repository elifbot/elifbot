# -*- coding: utf-8 -*-
import time

class SimulationOrderLifecycle:
    def __init__(self, config):
        self.config = config

    def process_trailing_stop(self, position, current_price) -> tuple:
        """Düzeltilmiş trailing stop mantığı: +%0.9'dan geri dönünce de tetiklenir, gerçekçi çıkış fiyatı hesaplar"""
        side = position['side']
        entry_price = position['entry_price']
        highest = position.get('highest_price', entry_price)
        lowest = position.get('lowest_price', entry_price)
        ts_pct = self.config['TRAILING_STOP_PERCENT']

        triggered = False
        exit_price = current_price

        if side == 'long':
            if current_price > highest:
                position['highest_price'] = current_price
                highest = current_price
            
            # %1 trailing stop eşiği
            stop_threshold = highest * (1.0 - ts_pct)
            if current_price <= stop_threshold:
                triggered = True
                exit_price = stop_threshold
        else:
            if current_price < lowest:
                position['lowest_price'] = current_price
                lowest = current_price
            
            stop_threshold = lowest * (1.0 + ts_pct)
            if current_price >= stop_threshold:
                triggered = True
                exit_price = stop_threshold

        return triggered, exit_price
