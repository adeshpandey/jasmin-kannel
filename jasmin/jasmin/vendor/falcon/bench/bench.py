#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright 2014 by Rackspace Hosting, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import argparse
from collections import defaultdict, deque
from decimal import Decimal
import gc
import inspect
import random
import sys
import timeit

try:
    import cProfile
except ImportError:
    import profile as cProfile

try:
    import guppy
except ImportError:
    heapy = None
else:
    heapy = guppy.hpy()

try:
    import pprofile
except ImportError:
    pprofile = None

from falcon.bench import create  # NOQA
import falcon.testing as helpers

# NOTE(kgriffs): Based on testing, these values provide a ceiling that's
# several times higher than fast x86 hardware can achieve today.
#
#   int(1.2**60) = 56347
#
ITER_DETECTION_MAX_ATTEMPTS = 60
ITER_DETECTION_MULTIPLIER = 1.2

# NOTE(kgriffs): Benchmark duration range, in seconds, to target
ITER_DETECTION_DURATION_MIN = 0.2
ITER_DETECTION_DURATION_MAX = 2.0


def bench(func, iterations, stat_memory):
    gc.collect()
    heap_diff = None

    if heapy and stat_memory:
        heap_before = heapy.heap()

    total_sec = timeit.timeit(func, setup=gc.enable, number=iterations)

    if heapy and stat_memory:
        heap_diff = heapy.heap() - heap_before

    sec_per_req = Decimal(str(total_sec)) / Decimal(str(iterations))

    sys.stdout.write('.')
    sys.stdout.flush()

    return (sec_per_req, heap_diff)


def determine_iterations(func):
    # NOTE(kgriffs): Algorithm adapted from IPython's magic timeit
    # function to determine iterations so that 0.2 <= total time < 2.0
    iterations = ITER_DETECTION_MULTIPLIER
    for __ in range(1, ITER_DETECTION_MAX_ATTEMPTS):
        gc.collect()

        total_sec = timeit.timeit(
            func,
            setup=gc.enable,
            number=int(iterations)
        )

        if total_sec >= ITER_DETECTION_DURATION_MIN:
            assert total_sec < ITER_DETECTION_DURATION_MAX
            break

        iterations *= ITER_DETECTION_MULTIPLIER

    return int(iterations)


def profile(name, env, filename=None, verbose=False):
    if filename:
        filename = name + '-' + filename
        print('Profiling %s ==> %s' % (name, filename))

    else:
        filename = None

        title = name + ' profile'
        print()
        print('=' * len(title))
        print(title)
        print('=' * len(title))

    func = create_bench(name, env)

    gc.collect()
    code = 'for x in range(10000): func()'

    if verbose:
        if pprofile is None:
            print('pprofile not found. Please install pprofile and try again.')
            return

        pprofile.runctx(code, locals(), globals(), filename=filename)

    else:
        cProfile.runctx(code, locals(), globals(),
                        sort='tottime', filename=filename)


def exhaust(iterator_or_generator):
    # from https://docs.python.org/dev/library/itertools.html#itertools-recipes
    deque(iterator_or_generator, maxlen=0)


BODY = helpers.rand_string(10240, 10240)  # NOQA
HEADERS = {'X-Test': 'Funky Chicken'}  # NOQA


def create_bench(name, env):
    srmock = helpers.StartResponseMock()

    function = name.lower().replace('-', '_')
    app = eval('create.{0}(BODY, HEADERS)'.format(function))

    def bench():
        app(env, srmock)
        if srmock.status != '200 OK':
            raise AssertionError(srmock.status + ' != 200 OK')

    def bench_generator():
        exhaust(app(env, srmock))
        if srmock.status != '200 OK':
            raise AssertionError(srmock.status + ' != 200 OK')

    if inspect.isgeneratorfunction(app):
        return bench_generator
    else:
        return bench


def consolidate_datasets(datasets):
    results = defaultdict(list)
    for dataset in datasets:
        for name, sec_per_req, _ in dataset:
            results[name].append(sec_per_req)

    return [(name, min(vector)) for name, vector in results.items()]


def round_to_int(dec):
    return int(dec.to_integral_value())


def avg(array):
    return sum(array) / len(array)


def hello_env():
    request_headers = {'Content-Type': 'application/json'}
    return helpers.create_environ('/hello/584/test',
                                  query_string='limit=10&thing=ab',
                                  headers=request_headers)


def queues_env():
    request_headers = {'Content-Type': 'application/json'}
    path = ('/v1/852809/queues/0fd4c8c6-bd72-11e2-8e47-db5ebd4c8125'
            '/claims/db5ebd4c8125')

    qs = 'limit=10&thing=a%20b&x=%23%24'
    return helpers.create_environ(path, query_string=qs,
                                  headers=request_headers)


def get_env(framework):
    return queues_env() if framework == 'falcon-ext' else hello_env()


def run(frameworks, trials, iterations, stat_memory):
    # Skip any frameworks that are not installed
    for name in frameworks:
        try:
            create_bench(name, hello_env())
        except ImportError as ex:
            print(ex)
            print('Skipping missing library: ' + name)
            del frameworks[frameworks.index(name)]

    print()

    if not frameworks:
        print('Nothing to do.\n')
        return

    datasets = []

    benchmarks = []
    for name in frameworks:
        bm = create_bench(name, get_env(name))
        bm_iterations = iterations if iterations else determine_iterations(bm)
        benchmarks.append((name, bm_iterations, bm))
        print('{}: {} iterations'.format(name, bm_iterations))

    print()

    for r in range(trials):
        random.shuffle(frameworks)

        sys.stdout.write('Benchmarking, Trial %d of %d' %
                         (r + 1, trials))
        sys.stdout.flush()

        dataset = []
        for name, bm_iterations, bm in benchmarks:
            sec_per_req, heap_diff = bench(
                bm,
                bm_iterations,
                stat_memory
            )

            dataset.append((name, sec_per_req, heap_diff))

        datasets.append(dataset)
        print('done.')

    return datasets


def main():
    frameworks = [
        'bottle',
        'falcon',
        'falcon-ext',
        'flask',
        'pecan',
        'werkzeug'
    ]

    parser = argparse.ArgumentParser(description='Falcon benchmark runner')
    parser.add_argument('-b', '--benchmark', type=str, action='append',
                        choices=frameworks, dest='frameworks', nargs='+')
    parser.add_argument('-i', '--iterations', type=int, default=0)
    parser.add_argument('-t', '--trials', type=int, default=10)
    parser.add_argument('-p', '--profile', type=str,
                        choices=['standard', 'verbose'])
    parser.add_argument('-o', '--profile-output', type=str, default=None)
    parser.add_argument('-m', '--stat-memory', action='store_true')
    args = parser.parse_args()

    if args.stat_memory and heapy is None:
        print('WARNING: Guppy not installed; memory stats are unavailable.\n')

    if args.frameworks:
        frameworks = args.frameworks

    # Normalize frameworks type
    normalized_frameworks = []
    for one_or_many in frameworks:
        if isinstance(one_or_many, list):
            normalized_frameworks.extend(one_or_many)
        else:
            normalized_frameworks.append(one_or_many)

    frameworks = normalized_frameworks

    # Profile?
    if args.profile:
        for name in frameworks:
            profile(name, get_env(name),
                    filename=args.profile_output,
                    verbose=(args.profile == 'verbose'))

        print()
        return

    # Otherwise, benchmark
    datasets = run(frameworks, args.trials, args.iterations,
                   args.stat_memory)

    dataset = consolidate_datasets(datasets)
    dataset = sorted(dataset, key=lambda r: r[1])
    baseline = dataset[-1][1]

    print('\nResults:\n')

    for i, (name, sec_per_req) in enumerate(dataset):
        req_per_sec = round_to_int(Decimal(1) / sec_per_req)
        us_per_req = (sec_per_req * Decimal(10 ** 6))
        factor = round_to_int(baseline / sec_per_req)

        print('{3}. {0:.<15s}{1:.>06d} req/sec or {2: >3.2f} ??s/req ({4}x)'.
              format(name, req_per_sec, us_per_req, i + 1, factor))

    if heapy and args.stat_memory:
        print()

        for name, _, heap_diff in datasets[0]:
            title = 'Memory change induced by ' + name
            print()
            print('=' * len(title))
            print(title)
            print('=' * len(title))
            print(heap_diff)

    print()


if __name__ == '__main__':
    main()
