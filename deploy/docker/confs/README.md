We assume you have created a local user and a group named `lega`. If not, you can do it with

    groupadd -r lega
    useradd -M -g lega lega


Generate the service and master keys with:

	crypt4gh-keygen -f --pk confs/service.pubkey --sk confs/service.seckey -C "service_key@LocalEGA"
	crypt4gh-keygen -f --pk confs/master.pubkey --sk confs/master.seckey -C "master_key@LocalEGA"

	# update the permissions
	chown lega:lega confs/{master,service}.{pubkey,seckey}
	chmod 600 confs/{master,service}.{pubkey,seckey}

Note: You will get prompted for the passphrase. Save it and update `confs/ingester.ini` accordingly, with the proper filepath and the chosen passphrase. (it is _not_ recommended _not to use_ any passphrase).


We provide 2 pre-generated dummy keys with the passphrase 'hello'.


```bash
	# Create the directories (some with the setgid bit)
	mkdir -p data/{inbox,staging,vault,vault.bkp}

	# Change the ownership
	chown lega:lega data/{inbox,staging,vault,vault.bkp}

	# Change the access permissions
	chmod 700 data/staging
	chmod 750 data/vault  # lega group needs r,x in order to distribute files
	chmod 700 data/vault.bkp
```
Adjust the paths in the `docker-compose.yml` file and the `confs/*.ini` configuration files if you didn't create the directory in other location than `data/...`.


# postgres configurations

In the `pg.conf` file, update the `crypt4gh.master_seckey` secret with the hex value of the master private key.  
You can run the following python snippet to get it: (you need the `crypt4gh` package: `pip install crypt4gh`).

```python
import crypt4gh.keys

key_content = crypt4gh.keys.get_private_key("/path/to/master.key.sec", lambda: "passphrase")

print(key_content.hex())
```

The `pg_hba.conf` controls the network accesses to the database.  
The default supplied one is not very restrictive, and you should adjust it in your production environment.  
(For example, by enabling TLS/SSL in the `pg.conf` and restricting network CIDRs in `pg_hba.conf`).
