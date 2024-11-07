# Astrolabe

Configure Astrolabe to discover your network topology by introspecting runtime environments.

## Prerequisites
* python 3.10 or greater available at `/usr/local/env python3`
* Neo4J Installed
  * NEO4J environment variables required for access:
    * NEO4J_URL
    * NEO4J_USERNAME
    * NEO4J_PASSWORD
* AWS CLI Login authenticated
* Kubectl login authenticated
* SSH login setup for SSH-able EC2 machines w/out specifying key or password (using ssh-config file and ssh-add)

## Limitations
* Currently assumes usaged of AWS EC2 and also kubernetes (Planned improvement in roadmap)
* Currently only supports 1 AWS account (Planned improvement in roadmap)
* Currently only supports 1 kubernetes cluster (Planned improvement in roadmap)
  

## Configure
The following arguments are required to run astrolabe.  These may be specified in a config file, per the [example conf file](./astrolabe.conf.example) or passed as CLI args.
1. Required agruments
   1.  `--aws-service-name-tag`: Assumed that the name of your service/application is tagged in AWS by this tag name
   2.  `--k8s-namespace`: Assumes one kubernetes cluster and namespace, configured here
   3.  `--ssh-name-command`: Astrolabe looks for the name of a service within a VM by executing this shell command which you will specify here
   4.  `--seeds`: A seed node or nodes to start discovery with.
1. Run `astrolabe --help` for all available commands and `astrolabe discover --help` and `astrolabe export --help` for command specific configuration.



## Use
#### 1 Run in `discover` mode:

```
$ astrolabe discover -s ssh:$SEED_IP
foo [seed] (10.1.0.26)
 |--HAP--? {ERR:TIMEOUT} UNKNOWN [port:80] (some-unreachable.host.local)
 |--HAP--> mono [port:80/443] (10.0.0.123)
 |          |--NSQ--? {ERR:NULL_ADDRESS} UNKNOWN [some-multiplexor] (None)
```


#### 3 Run in `export` mode
Note: unlike the `discover` command, `export` is written to stand alone and parse the default json file in `outputs/.lastrun.json` it requires no arguments by default.
It will by default render the "last run" automatically dumped to .lastrun.json.  Or you can pass in `-f` to load a specific file.  The default exporter is `ascii` unless a different exporter is passed in, as in `--output graphviz`

``` 
$ astrolabe render
foo [seed] (10.1.0.26)
 |--HAP--? {ERR:TIMEOUT} UNKNOWN [port:80] (some-unreachable.host.local)
 |--HAP--> mono [port:80/443] (10.0.0.123)
 |          |--NSQ--? {ERR:NULL_ADDRESS} UNKNOWN [some-multiplexor] (None)
...
```

## Advanced Usage - Profile Strategies
* TO BE COMPLETED

## Advanced Usage - Provider/Plugin Development
* TO BE COMPLETED

## Help
```
./astrolabe --help
```


## Contributing

### Unit Tests
#### Design Choices
* `pytest` is used instead of `unittest` for more succinct test/reporting
* `pytest-mock` is used for mocks, so you will see the `mocker` fixtures passed around magically for mocking. It is used in combination with the parameter `new=sentinel.devnull` in order to not pass the patched mock to the test function. 
* Arrange, Act, Assert test style is used
* mocks are preferred for dependencies over production objects
* tests of objects are organized into a TestClass named after the object 1) for organization and 2) so that IDEs can find the test/subject relationship.
* tests are named in the following format: `"test_{name_of_function}_case_{description_of_case}"`
* the string 'dummy' is used to indicate that a value is assigned solely to meet argument requirements, but unused otherwise
* fixtures are placed in conftest.py only if they are use in common between test packages, otherwise please keep them in the package they are used in
* the idiomatic references 'foo', 'bar', 'baz', 'buz', etc are used when passing stub values around.  if you choose not to follow precedent:  please use something obvious like 'stub1', 'stub2', etc

#### Run tests
```
pytest
```

#### Run coverage
```
pytest --cov=water_spout tests
```

### Static Code Analysis
```
prospector --profile .prospector.yaml 
```

