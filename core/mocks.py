class MockEventBus:
    def subscribe(self, topic, callback):
        pass

    def unsubscribe(self, topic, callback):
        pass

    async def publish(self, topic, event):
        pass


class MockOrderManager:
    def get_order_by_client_id(self, client_order_id):
        return None

    def get_active_orders(self, strategy_name=None):
        return []

    def get_order_history(self, strategy_name=None):
        return []
