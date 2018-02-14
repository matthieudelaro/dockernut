This repo is the PoC version of [Nut](https://github.com/matthieudelaro/nut). This repo is completely outdated and should not be used. But if you're looking for some funny attempt of turning Docker Compose into something new, then have fun reading through :)


Donut, Docker Nut
==============


Docker Nut sets up dev environments based on Docker containers.
It aims to manage environments as easily as one installs packages with npm/bower/etc,
without messing up your computer's configuration. Everything happens in containers.
As npm, Donut stores some configuration files in .nut directory, such as the environment
configuration files.

To begin with, create a file nut.yml (example below) in your working directory, and run :

nut build  # to build the app
nut run  # to run the app
nut cmd helloworld  # you can define custom commands in nut.yml file
nut exe ls -la  # you can run whatever command in the environment

A `nut.yml` describing a project looks like this:

    go:  # name of the environment
      env:
        path: exampleOfLocalNutFile/go/nut.yml  # path to a nut.yml file describing an environment
        # You can also install the environment with a url:
        # url: https://raw.githubusercontent.com/matthieudelaro/donut/master/go/nut.yml
      commands:  # defined custom commands / macros to run in the container with "nut cmd NAME"
        helloworld:  # custom command called "helloworld"
          - echo "Hello World! ..."
          - echo "... Welcome to Docker Nut, Donut."
        # By convention, custom commands should be in lowercase.
        # you can also override RUN, BUILD, etc, which are called by "nut run", "nut build", etc.


On the other hand, the `nut.yml` describing an environment looks like this:

    nut:  # this doesn't really matter yet. Just stick to this to have the same pattern for every environment
      env:
        image: golang:latest  # which image from Docker Hub to use
        # or dockerfile: future feature to build directly from a docker file
      commands:  # declare commands of the environments.
        BUILD:
          - go build -o output
        RUN:
          - ./output
        TEST:
          - echo "Nothing to test yet"
        # By convention, uppercase means that it is a command predefined by nut ("nut run", "nut build", etc)


For more information about the Nut file, see the
[example](tests/nut/)

Releasing
---------

This project is in a very early stage and is to evolve quickly.
To test Donut, set up a development environment by running `python3 setup.py develop`.
This will install the dependencies and set up a symlink from your `nut`
executable to the checkout of the repository. When you now run
`nut` from anywhere on your machine, it will run your development
version of Donut.
