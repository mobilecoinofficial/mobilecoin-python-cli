from contextlib import contextmanager
from decimal import Decimal
import json
import sys
import tempfile
import time

from mobilecoin import cli, Client, WalletAPIError, pmob2mob


def main():
    # c = Client(verbose=True)
    c = Client(verbose=False)

    source_wallet = sys.argv[1]

    # Create a test wallet database, and start the server.
    db_file = tempfile.NamedTemporaryFile(suffix='.db', prefix='test_wallet_', delete=False)
    cli.config['wallet-db'] = db_file.name
    cli_obj = cli.CommandLineInterface()
    cli_obj.stop()
    time.sleep(0.5)  # Wait for other servers to stop.
    cli_obj.start(bg=True)
    time.sleep(1)  # Wait for the server to start listening.

    # Start and end with an empty wallet.
    try:
        check_wallet_empty(c)
        test_errors(c)
        test_account_management(c)
        test_transactions(c, source_wallet)
        check_wallet_empty(c)
    except Exception:
        print('FAIL')
        raise
    else:
        print('ALL PASS')
        cli_obj.stop()  # Only stop the server if there were no errors.


def test_errors(c):
    print('test_errors')

    try:
        c.get_account('invalid')
    except WalletAPIError:
        pass
    else:
        raise AssertionError()

    print('PASS')


def test_account_management(c):
    print('test_account_management')

    # Create an account.
    account = c.create_account()
    account_id = account['account_id']

    # Get accounts.
    account_2 = c.get_account(account_id)
    assert account == account_2

    accounts = c.get_all_accounts()
    account_ids = list(accounts.keys())
    assert account_ids == [account_id]
    assert accounts[account_id] == account

    # Rename account.
    assert account['name'] == ''
    c.update_account_name(account_id, 'X')
    account = c.get_account(account_id)
    assert account['name'] == 'X'

    # Remove the created account.
    c.remove_account(account_id)

    # Import an account from entropy.
    entropy = '0000000000000000000000000000000000000000000000000000000000000000'
    account = c.import_account(entropy)
    account_id = account['account_id']
    assert (
        account['main_address']
        == '6UEtkm1rieLhuz2wvELPHdGiCb96zNnW856QVeGLvYzE7NhmbG1MxnoSPGqyVfEHDvxzQmaURFpZcxT9TSypVgRVAusr7svtD1TcrYj92Uh'
    )

    # Export secrets.
    secrets = c.export_account_secrets(account_id)
    assert secrets['entropy'] == entropy
    assert (
        secrets['account_key']['view_private_key']
        == '0a20b0146de8cd8f5b7962f9e74a5ef0f3e58a9550c9527ac144f38729f0fd3fed0e'
    )
    assert (
        secrets['account_key']['spend_private_key']
        == '0a20b4bf01a77ed4e065e9082d4bda67add30c88e021dcf81fc84e6a9ca2cb68e107'
    )
    c.remove_account(account_id)

    print('PASS')


def test_transactions(c, source_wallet):
    print('test_transactions')

    print('Loading from', source_wallet)

    # Import an account with money.
    entropy, block, _ = cli._load_import(source_wallet)
    source_account = c.import_account(entropy, block=block)

    try:
        test_transactions_inner(c, source_account)
    except Exception:
        # If the test fails, show account entropy so we can put the funds back.
        print()
        print('main address')
        print(source_account['main_address'])
        accounts = c.get_all_accounts()
        for account_id in accounts.keys():
            if account_id == source_account['account_id']:
                continue
            secrets = c.export_account_secrets(account_id)
            print()
            print(account_id)
            print(secrets['entropy'])


def test_transactions_inner(c, source_account):
    source_account_id = source_account['account_id']

    # Check its balance.
    balance = c.poll_balance_until_synced(source_account_id)
    assert pmob2mob(balance['unspent_pmob']) >= 1

    # List txos.
    txos = c.get_all_txos_for_account(source_account_id)
    assert len(txos) > 0

    # Send transactions and ensure they show up in the transaction list.
    dest_account = c.create_account()
    dest_account_id = dest_account['account_id']

    transaction_log = c.build_and_submit_transaction(source_account_id, 0.1, dest_account['main_address'])
    tx_index = int(transaction_log['submitted_block_index'])
    balance = c.poll_balance_until_synced(dest_account_id, tx_index + 1)
    print('actual', pmob2mob(balance['unspent_pmob']))
    print('expected', Decimal('0.1'))
    assert pmob2mob(balance['unspent_pmob']) == Decimal('0.1')

    transaction_log = c.build_and_submit_transaction(dest_account_id, 0.09, source_account['main_address'])
    tx_index = int(transaction_log['submitted_block_index'])
    balance = c.poll_balance_until_synced(dest_account_id, tx_index + 1)
    print('actual', pmob2mob(balance['unspent_pmob']))
    print('expected', Decimal('0.0'))
    assert pmob2mob(balance['unspent_pmob']) == Decimal('0.0')

    c.remove_account(dest_account_id)
    c.remove_account(source_account_id)

    print('PASS')


def check_wallet_empty(c):
    with quiet(c):
        accounts = c.get_all_accounts()
        assert accounts == {}, 'Wallet not empty!'


@contextmanager
def quiet(c):
    old_verbose = c.verbose
    c.verbose = False
    yield
    c.verbose = old_verbose


if __name__ == '__main__':
    main()
