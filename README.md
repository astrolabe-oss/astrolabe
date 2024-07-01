# Astrolabe

Configure Astrolabe to discover your network topology by introspecting runtime environments.

## Prerequisites
* python 3.8 available at `/usr/local/env python3`
  * python >= 3.7 was chosen in order to use python dataclasses
  * python >= 3.8 was chosen in order to use unittest.mock AsyncMock

## Configure Astrolabe in 7 easy steps!
1. Review the example project in [examples/example-project](examples/example-project)
1. Start a new project / empty folder
    1. `mkdir new_project && cd new_project`
    1. `venv'
    1. `echo "git+ssh://git@github.com/guruai/astrolabe.git#egg=astrolabe" > requirements.txt`
    1. `pip install -r requirements.txt`
1. Configure astrolabe.d - the configuration folder with which you will describe your network graph to astrolabe
    1. `mkdir astrolabe.d`
    1. Create your `...ProfileStrategy.yaml` file(s).
        1. Please see [examples/ExampleSSHProfileStrategy.yaml](examples/ExampleSSHDiscoveryStrategy.yaml) for example/documentation.
    2. Crate `web.yaml` file  
        1. "Providers", "skips" , and "Hints" are all defined in [examples/network.yaml](examples/web.yaml). 
1. Run `astrolabe --help` for all available commands and `astrolabe discover --help` and `astrolabe export --help` for command specific configuration.
1. Disable builtin provider with the argument `--disable-providers ssh aws k8s`
1. Set any configurations which are known to be required for every run in `discover.conf` see [./examples/astrolabe.conf.example](./examples/discover.conf.example)
  1. Hint: `astrolabe.conf` is always inherited, but you can create different profiles such as `astrolabe.prod.conf` and reference them with the `--config-file` arg

Note: unlike the `discover` command, `export` is written to stand alone and parse the default json file in `outputs/.lastrun.json` it requires no arguments by default.

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
It will by default render the "last run" automatically dumped to .lastrun.json.  Or you can pass in `-f` to load a specific file.  The default exporter is `ascii` unless a different exporter is passed in, as in `--output graphviz`

``` 
$ astrolabe render
foo [seed] (10.1.0.26)
 |--HAP--? {ERR:TIMEOUT} UNKNOWN [port:80] (some-unreachable.host.local)
 |--HAP--> mono [port:80/443] (10.0.0.123)
 |          |--NSQ--? {ERR:NULL_ADDRESS} UNKNOWN [some-multiplexor] (None)
...
```

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

