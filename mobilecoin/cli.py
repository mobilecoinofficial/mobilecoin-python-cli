import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess

from mnemonic import Mnemonic

from mobilecoin.client import (
    Client,
    pmob2mob,
)

NETWORK = 'testnet'
assert NETWORK in ['testnet', 'mainnet']
MC_DATA = Path.home() / '.mobilecoin' / NETWORK
LOG_LOCATION = MC_DATA / 'wallet_server_log.txt'


class CommandLineInterface:

    def main(self):
        self._create_parsers()

        args = self.parser.parse_args()
        args = vars(args)
        command = args.pop('command')
        if command is None:
            self.parser.print_help()
            exit(1)

        self.verbose = args.pop('verbose')
        self.client = Client(verbose=self.verbose)

        # Dispatch command.
        setattr(self, 'import', self.import_)  # Can't name a function "import".
        command_func = getattr(self, command)
        command_func(**args)

    def _create_parsers(self):
        self.parser = argparse.ArgumentParser(
            prog='mobilecoin',
            description='MobileCoin command-line wallet.',
        )
        self.parser.add_argument('-v', '--verbose', action='store_true', help='Show more information.')

        subparsers = self.parser.add_subparsers(dest='command', help='Commands')

        self.start_args = subparsers.add_parser('start', help='Start the local MobileCoin wallet server.')
        self.start_args.add_argument('--offline', action='store_true', help='Start in offline mode.')
        self.start_args.add_argument('--bg', action='store_true',
                                     help='Start server in the background, stop with "mobilecoin stop".')

        self.stop_args = subparsers.add_parser('stop', help='Stop the local MobileCoin wallet server.')

        self.create_args = subparsers.add_parser('create', help='Create a new account.')
        self.create_args.add_argument('-n', '--name', help='Account name.')
        self.create_args.add_argument('-b', '--block', type=int,
                                      help='Block index at which to start the account. No transactions before this block will be loaded.')

        self.import_args = subparsers.add_parser('import', help='Import an account.')
        self.import_args.add_argument('seed', help='Account seed phrase, seed file, or root entropy hex.')
        self.import_args.add_argument('-n', '--name', help='Account name.')
        self.import_args.add_argument('-b', '--block', type=int,
                                      help='Block index at which to start the account. No transactions before this block will be loaded.')

        self.export_args = subparsers.add_parser('export', help='Export seed phrase.')
        self.export_args.add_argument('account_id', help='Account ID code.')

        self.delete_args = subparsers.add_parser('delete', help='Delete an account from local storage.')
        self.delete_args.add_argument('account_id', help='Account ID code.')

        self.list_args = subparsers.add_parser('list', help='List accounts.')

        self.history_args = subparsers.add_parser('history', help='Show account transaction history.')
        self.history_args.add_argument('account_id', help='Account ID code.')

        self.send_args = subparsers.add_parser('send', help='Send a transaction.')
        self.send_args.add_argument('from_account_id', help='Account ID to send from.')
        self.send_args.add_argument('amount', help='Amount of MOB to send.', type=float)
        self.send_args.add_argument('to_address', help='Address to send to.')

    def _load_account_prefix(self, prefix):
        accounts = self.client.get_all_accounts()
        matching_ids = [
            a_id for a_id in accounts.keys()
            if a_id.startswith(prefix)
        ]
        if len(matching_ids) == 0:
            print('Could not find account starting with', prefix)
            exit(1)
        elif len(matching_ids) == 1:
            account_id = matching_ids[0]
            return accounts[account_id]
        else:
            print('Multiple matching matching ids: {}'.format(', '.join(matching_ids)))
            exit(1)

    def start(self, offline=False, bg=False):
        if NETWORK == 'testnet':
            wallet_server_command = ['./full-service-testnet']
        elif NETWORK == 'mainnet':
            wallet_server_command = ['./full-service-mainnet']

        wallet_server_command += [
            '--wallet-db', str(MC_DATA / 'wallet-db/wallet.db'),
            '--ledger-db', str(MC_DATA / 'ledger-db'),
        ]
        if offline:
            wallet_server_command += [
                '--offline',
            ]
        else:
            if NETWORK == 'testnet':
                wallet_server_command += [
                    '--peer mc://node1.test.mobilecoin.com/',
                    '--peer mc://node2.test.mobilecoin.com/',
                    '--tx-source-url https://s3-us-west-1.amazonaws.com/mobilecoin.chain/node1.test.mobilecoin.com/',
                    '--tx-source-url https://s3-us-west-1.amazonaws.com/mobilecoin.chain/node2.test.mobilecoin.com/',
                ]
            elif NETWORK == 'mainnet':
                wallet_server_command += [
                    '--peer', 'mc://node1.prod.mobilecoinww.com/',
                    '--peer', 'mc://node2.prod.mobilecoinww.com/',
                    '--tx-source-url', 'https://ledger.mobilecoinww.com/node1.prod.mobilecoinww.com/',
                    '--tx-source-url', 'https://ledger.mobilecoinww.com/node2.prod.mobilecoinww.com/',
                ]
        if bg:
            wallet_server_command += [
                '>', str(LOG_LOCATION), '2>&1'
            ]

        if NETWORK == 'testnet':
            print('Starting TestNet wallet server...')
        elif NETWORK == 'mainnet':
            print('Starting MobileCoin wallet server...')

        if self.verbose:
            print(' '.join(wallet_server_command))

        MC_DATA.mkdir(parents=True, exist_ok=True)
        (MC_DATA / 'ledger-db').mkdir(exist_ok=True)
        (MC_DATA / 'wallet-db').mkdir(exist_ok=True)

        os.environ['RUST_LOG'] = 'info'
        os.environ['mc_ledger_sync'] = 'info'
        if bg:
            subprocess.Popen(' '.join(wallet_server_command), shell=True)
            print('Started, view log at {}.'.format(LOG_LOCATION))
            print('Stop server with "mobilecoin stop".')
        else:
            subprocess.run(' '.join(wallet_server_command), shell=True)

    def stop(self):
        if self.verbose:
            print('Stopping MobileCoin wallet server...')
        if NETWORK == 'testnet':
            subprocess.Popen(['killall', '-v', 'full-service-testnet'])
        elif NETWORK == 'mainnet':
            subprocess.Popen(['killall', '-v', 'full-service'])

    def create(self, **args):
        account = self.client.create_account(**args)
        account_id = account['account_id']
        print('Created a new account.')
        print(account_id[:6], account['name'])

    def import_(self, seed, **args):
        entropy, block = _load_import(seed)
        if args['block'] is None and block is not None:
            args['block'] = block
        account = self.client.import_account(entropy, **args)
        account_id = account['account_id']
        balance = self.client.get_balance_for_account(account_id)

        print('Imported account.')
        print()
        _print_account(account, balance)
        print()

    def export(self, account_id):
        account = self._load_account_prefix(account_id)
        account_id = account['account_id']
        balance = self.client.get_balance_for_account(account_id)

        print('You are about to export the seed phrase for this account:')
        print()
        _print_account(account, balance)
        print()
        print('Anyone who has access to the seed phrase can spend all the')
        print('funds in the account. Keep the exported file safe and private!')
        if not confirm('Really write account seed phrase to a file? (Y/N) '):
            print('Cancelled.')
            return

        secrets = self.client.export_account_secrets(account_id)
        filename = 'mobilecoin_seed_phrase_{}.json'.format(account_id[:16])
        _save_export(account, secrets, filename)
        print(f'Wrote {filename}.')

    def delete(self, account_id):
        account = self._load_account_prefix(account_id)
        account_id = account['account_id']
        balance = self.client.get_balance_for_account(account_id)

        amount = pmob2mob(balance['unspent_pmob'])
        if balance['is_synced'] is True and amount == 0:
            print('Account {} has 0 MOB.'.format(account_id[:6]))
        else:
            print('You are about to delete this account:')
            print()
            _print_account(account, balance)
            print()
            print('You will lose access to the funds in this account unless you')
            print('restore it from the seed phrase.')
            if not confirm('Continue? (Y/N) '):
                print('Cancelled.')
                return

        self.client.delete_account(account_id)
        print('Deleted.')

    def list(self, **args):
        accounts = self.client.get_all_accounts(**args)

        if len(accounts) == 0:
            print('No accounts.')
            return

        account_list = []
        for account_id, account in accounts.items():
            balance = self.client.get_balance_for_account(account_id)
            account_list.append((account_id, account, balance))

        for (account_id, account, balance) in account_list:
            total_blocks = int(balance['network_block_index'])
            offline = (total_blocks == 0)
            if offline:
                total_blocks = balance['local_block_index']
            print()
            _print_account(account, balance)

        print()

    def history(self, account_id):
        pass

    def send(self, from_account_id, amount, to_address):
        account = self._load_account_prefix(from_account_id)
        from_account_id = account['account_id']
        amount = Decimal(amount)

        print('\n'.join(
            'Sending {:.4f} MOB from account {} {}',
            'to address {}.'
        ).format(
            amount,
            from_account_id[:6],
            account['name'],
            to_address,
        ))
        if not confirm('Confirm? (Y/N) '):
            print('Cancelled.')
            return

        self.client.send_transaction(from_account_id, amount, to_address)
        print('Sent.')

    def prepare():
        pass

    def submit():
        pass


def confirm(message):
    confirmation = input(message)
    return confirmation.lower() in ['y', 'yes']


def _print_account(account, balance):
    account_id = account['account_id']

    total_blocks = int(balance['network_block_index'])
    offline = (total_blocks == 0)
    if offline:
        total_blocks = balance['local_block_index']

    print(account_id[:6], account['name'])
    print('  address', account['main_address'])
    print('  {:.4f} MOB ({}/{} blocks synced) {}'.format(
        pmob2mob(balance['unspent_pmob']),
        balance['account_block_index'],
        total_blocks,
        ' [offline]' if offline else '',
    ))


def _load_import(seed):
    # Try to use it as hexadecimal root entropy.
    try:
        b = bytes.fromhex(seed)
        if len(b) == 32:
            entropy = b.hex()
            return entropy, None
    except ValueError:
        pass

    # Try to interpret it as a BIP39 mnemonic.
    try:
        entropy = Mnemonic('english').to_entropy(seed).hex()
        return entropy, None
    except (ValueError, LookupError):
        pass

    # Last chance, try to open it as a JSON filename.
    with open(seed) as f:
        data = json.load(f)
    return data['root_entropy'], data['first_block_index']


def _save_export(account, secrets, filename):
    entropy = secrets['entropy']
    seed_phrase = Mnemonic('english').to_mnemonic(bytes.fromhex(entropy))

    export_data = {
        "seed_phrase": seed_phrase,
        "root_entropy": entropy,
        "account_id": account['account_id'],
        "account_name": account['name'],
        "account_key": secrets['account_key'],
        "first_block_index": account['first_block_index'],
    }
    with open(filename, 'w') as f:
        json.dump(export_data, f, indent=4)
        f.write('\n')
