from quik_python import Quik
q = Quik()
async def main(): 
    await q.initialize()
    print(dir(q.orders))
    print(dir(q.trades))
    print(dir(q.candles))

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())