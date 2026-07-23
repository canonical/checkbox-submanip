Introduction
============

Submanip is a Checkbox submission editor. You can use it to modify test
results and comments. The result is saved as a new submission archive.

How to run
==========

Submanip requires Flask and Checkbox-ng (>= 1.6.0) to run. You can deploy
it in a LXC container, for instance, using the following commands:

```
$ sudo add-apt-repository ppa:hardware-certification/public
$ sudo apt install python3-flask checkbox-ng
$ export FLASK_APP=submanip.py
$ flask run --host=0.0.0.0 --port=8080
```

You should see something like:

```
 * Serving Flask app "submanip.py"
 * Environment: production
   WARNING: Do not use the development server in a production environment.
   Use a production WSGI server instead.
 * Debug mode: off
 * Running on http://0.0.0.0:8080/ (Press CTRL+C to quit)
```

Depending on the IP of the device running Flask, you can access the app by
going to http://<IP>:8080/.

Flask has a debug mode that can be very useful for debugging purposes. Enable
it by setting the `FLASK_DEBUG` environment variable:

```
$ export FLASK_APP=submanip.py
$ export FLASK_DEBUG=1
$ flask run --host=0.0.0.0 --port=8080
```

If you intend to have this webapp run all the time, you can make use of a
systemd service file that is available in `systemd/submanip.service`.


How to run submanip in OCI compatible container
==========

1. Install docker or other OCI compatible toolset, such as podman.
```shell
sudo apt install podman
```
2. Build container
```shell
podman build -f containerized/Dockerfile -t submanip:v1 .
```
* -f : Select which Dockerfile you would like to use while Dockerfile isn't put on where you execute this command or the name isn't Dockerfile.
* -t : Set image tag, basic format is [name]:[version]. If you would like to push images to image repo, Full format is [repo_struct]/[name]:[version].
* The dot at the end of command means where is the base point for Dockerfile to find file. PS: This base point couldn't be parent of where you are.
3. Start container
```shell
podman run -d -p 8080:8080 --name submanip submanip:v1
```
* -d : Run container as daemon.
* -p : [port of host]:[port inside container]. Default will block all internet access(in) from container.
* --name : name for running container, let you could control container without container ID.
4. open browser to localhost:8080, you should seee the website of Checkbox Submission Editor.
5. Stop submanip container
```shell
podman stop submanip
```
6. Restart container
```shell
podman restart submanip
```

