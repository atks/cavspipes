#!/usr/bin/env python3

# The MIT License
# Copyright (c) 2023 Adrian Tan <adrian_tan@nparks.gov.sg>
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the 'Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import os
import click
import sys
import re
import sys
from shutil import copy2
from datetime import datetime


@click.command()
@click.option(
    "-m",
    "--make_file",
    show_default=True,
    default="ilm_deploy_and_qc.mk",
    help="make file name",
)
@click.option("-r", "--run_id", required=True, help="Run ID")
@click.option("-i", "--illumina_dir", required=True, help="illumina directory")
@click.option(
    "-w",
    "--working_dir",
    default=os.getcwd(),
    show_default=True,
    help="working directory",
)
@click.option("-s", "--sample_file", required=True, help="sample file")
def main(make_file, run_id, illumina_dir, working_dir, sample_file):
    """
    Moves Illumina fastq files to a destination and performs QC

    e.g. vfp_generate_ilm_deploy_and_qc_pipeline -r ilm23 -i illumina_raw -i ilm23.sa
    """
    log_dir = f"{working_dir}/log"
    dest_dir = f"{working_dir}/{run_id}"
    fastq_dir = ""

    illumina_dir = os.path.abspath(illumina_dir)
    for dirpath, dirnames, filenames in os.walk(illumina_dir):
        for dirname in dirnames:
            if dirname == "Fastq":
                fastq_dir = os.path.join(dirpath, dirname)

    print("\t{0:<20} :   {1:<10}".format("make_file", make_file))
    print("\t{0:<20} :   {1:<10}".format("run_dir", run_id))
    print("\t{0:<20} :   {1:<10}".format("illumina_dir", illumina_dir))
    print("\t{0:<20} :   {1:<10}".format("working_dir", working_dir))
    print("\t{0:<20} :   {1:<10}".format("sample_file", sample_file))
    print("\t{0:<20} :   {1:<10}".format("dest_dir", dest_dir))
    print("\t{0:<20} :   {1:<10}".format("fastq_path", fastq_dir))

    # read sample file
    run = Run(run_id)
    with open(sample_file, "r") as file:
        index = 0
        for line in file:
            if not line.startswith("#"):
                index += 1
                sample_id, fastq1, fastq2 = line.rstrip().split("\t")
                run.add_sample(index, sample_id, fastq1, fastq2)

    # create directories in destination folder directory
    analysis_dir = f"{dest_dir}/analysis"
    new_dir = ""
    try:
        os.makedirs(log_dir, exist_ok=True)
        new_dir = analysis_dir
        os.makedirs(new_dir, exist_ok=True)
        for sample in run.samples:
            new_dir = f"{analysis_dir}/{sample.idx}_{sample.id}"
            os.makedirs(new_dir, exist_ok=True)
            new_dir = f"{analysis_dir}/{sample.idx}_{sample.id}/kraken2_result"
            os.makedirs(new_dir, exist_ok=True)
            new_dir = f"{analysis_dir}/{sample.idx}_{sample.id}/fastqc_result"
            os.makedirs(new_dir, exist_ok=True)
    except OSError as error:
        print(f"Directory {new_dir} cannot be created")

    # initialize
    pg = PipelineGenerator(make_file)
    multiqc_dep = ""

    # analyze
    fastqc_multiqc_dep = ""
    kraken2_multiqc_dep = ""
    kraken2_reports = ""

    for idx, sample in enumerate(run.samples):
        # copy the files
        src_fastq1 = f"{fastq_dir}/{sample.fastq1}"
        dst_fastq1 = f"{dest_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz"
        tgt = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz.OK"
        dep = ""
        cmd = f"cp {src_fastq1} {dst_fastq1}"
        pg.add(tgt, dep, cmd)

        src_fastq2 = f"{fastq_dir}/{sample.fastq2}"
        dst_fastq2 = f"{dest_dir}/{run.idx}_{sample.idx}_{sample.id}_R2.fastq.gz"
        tgt = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R2.fastq.gz.OK"
        dep = ""
        cmd = f"cp {src_fastq2} {dst_fastq2}"
        pg.add(tgt, dep, cmd)

        sample.fastq1 = dst_fastq1
        sample.fastq2 = dst_fastq2

        # fastqc
        fastqc = "/usr/local/FastQC-0.11.9/fastqc"
        fastqc_dir = f"{analysis_dir}/{sample.idx}_{sample.id}/fastqc_result"

        log = f"{log_dir}/{sample.idx}_{sample.id}_fastqc1.log"
        err = f"{log_dir}/{sample.idx}_{sample.id}_fastqc1.err"
        tgt = f"{log_dir}/{sample.idx}_{sample.id}_fastqc1.OK"
        dep = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz.OK"
        cmd = f"{fastqc} {sample.fastq1} -o {fastqc_dir} > {log} 2> {err}"
        pg.add(tgt, dep, cmd)
        fastqc_multiqc_dep += f" {tgt}"

        log = f"{log_dir}/{sample.idx}_{sample.id}_fastqc2.log"
        err = f"{log_dir}/{sample.idx}_{sample.id}_fastqc2.err"
        tgt = f"{log_dir}/{sample.idx}_{sample.id}_fastqc2.OK"
        dep = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz.OK"
        cmd = f"{fastqc} {sample.fastq2} -o {fastqc_dir} > {log} 2> {err}"
        pg.add(tgt, dep, cmd)
        fastqc_multiqc_dep += f" {tgt}"

        # kraken2
        kraken2 = "/usr/local/kraken2-2.1.2/kraken2"
        kraken2_std_db = "/usr/local/ref/kraken2/20210908_standard"
        input_fastq_file1 = f"{sample.fastq1}"
        input_fastq_file2 = f"{sample.fastq2}"
        output_dir = f"{analysis_dir}/{sample.idx}_{sample.id}/kraken2_result"
        report_file = f"{output_dir}/report.txt"
        log = f"{output_dir}/report.log"
        err = f"{output_dir}/run.log"
        dep = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz.OK {log_dir}/{run.idx}_{sample.idx}_{sample.id}_R2.fastq.gz.OK"
        if idx == 0:
            dep = f"{log_dir}/{run.idx}_{sample.idx}_{sample.id}_R1.fastq.gz.OK {log_dir}/{run.idx}_{sample.idx}_{sample.id}_R2.fastq.gz.OK"
        else:
            dep = f"{log_dir}/{run.idx}_{run.samples[idx-1].idx}_{run.samples[idx-1].id}_R1.fastq.gz.OK {log_dir}/{run.idx}_{run.samples[idx-1].idx}_{run.samples[idx-1].id}_R2.fastq.gz.OK {log_dir}/{run.samples[idx-1].idx}_{run.samples[idx-1].id}.kraken2.OK"
        tgt = f"{log_dir}/{sample.idx}_{sample.id}.kraken2.OK"
        kraken2_multiqc_dep += f" {tgt}"
        kraken2_reports += f" {log}"
        cmd = (
            f"set -o pipefail; {kraken2} --db {kraken2_std_db} --paired {input_fastq_file1} {input_fastq_file2} --use-names --report {report_file} "
            + '| perl -lane \'{@F=split("\\t"); $$F[2]=~/(.+) \(taxid (\d+)\)/; print "$$F[0]\\t$$F[1]\\t$$1\\t$$2\\t$$F[3]\\t$$F[4]"}\''
            + f"> {log} 2> {err}"
        )
        pg.add(tgt, dep, cmd)

        # plot kronatools radial tree
        kt_import_taxonomy = "/usr/local/KronaTools-2.8.1/bin/ktImportTaxonomy"
        output_dir = f"{analysis_dir}/{sample.idx}_{sample.id}/kraken2_result"
        input_txt_file = f"{output_dir}/report.log"
        output_html_file = f"{output_dir}/krona_radial_tree.html"
        log = f"{log_dir}/{sample.idx}_{sample.id}.krona_radial_tree.log"
        err = f"{log_dir}/{sample.idx}_{sample.id}.krona_radial_tree.err"
        dep = f"{log_dir}/{sample.idx}_{sample.id}.kraken2.OK"
        tgt = f"{log_dir}/{sample.idx}_{sample.id}.kraken2.krona_radial_tree.OK"
        cmd = f"{kt_import_taxonomy} -q 2 -t 4 {input_txt_file} -o {output_html_file} > {log} 2> {err}"
        pg.add(tgt, dep, cmd)

    multiqc = "/usr/local/bin/multiqc"

    # plot fastqc multiqc results
    analysis = "fastqc"
    output_dir = f"{analysis_dir}/all/{analysis}"
    log = f"{log_dir}/{analysis}.multiqc_report.log"
    err = f"{log_dir}/{analysis}.multiqc_report.err"
    dep = fastqc_multiqc_dep
    tgt = f"{log_dir}/{analysis}.multiqc_report.OK"
    cmd = f"cd {analysis_dir}; {multiqc} . -m fastqc -o {output_dir} -n {analysis} -dd -1 --no-ansi > {log} 2> {err}"
    pg.add(tgt, dep, cmd)

    # plot kraken2 multiqc results
    analysis = "kraken2"
    output_dir = f"{analysis_dir}/all/{analysis}"
    log = f"{log_dir}/{analysis}.multiqc_report.log"
    err = f"{log_dir}/{analysis}.multiqc_report.err"
    dep = kraken2_multiqc_dep
    tgt = f"{log_dir}/{analysis}.multiqc_report.OK"
    cmd = f"cd {analysis_dir}; {multiqc} . -m kraken -o {output_dir} -n {analysis} -dd -1 --no-ansi > {log} 2> {err}"
    pg.add(tgt, dep, cmd)

    # plot kronatools radial tree
    kt_import_taxonomy = "/usr/local/KronaTools-2.8.1/bin/ktImportTaxonomy"
    analysis = "kraken2"
    output_dir = f"{analysis_dir}/all/{analysis}"
    input_txt_files = kraken2_reports
    output_html_file = f"{output_dir}/krona_radial_tree.html"
    log = f"{log_dir}/{analysis}.krona_radial_tree.log"
    err = f"{log_dir}/{analysis}.krona_radial_tree.err"
    dep = f"{kraken2_multiqc_dep}"
    tgt = f"{log_dir}/{analysis}.krona_radial_tree.OK"
    cmd = f"{kt_import_taxonomy} -q 2 -t 4 {input_txt_files} -o {output_html_file} > {log} 2> {err}"
    pg.add(tgt, dep, cmd)

    # clean
    pg.add_clean(f"rm -fr {dest_dir} {log_dir}")

    # write make file
    print("Writing pipeline")
    pg.write()


class PipelineGenerator(object):
    def __init__(self, make_file):
        self.make_file = make_file
        self.tgts = []
        self.deps = []
        self.cmds = []
        self.clean_cmd = ""

    def add(self, tgt, dep, cmd):
        self.tgts.append(tgt)
        self.deps.append(dep)
        self.cmds.append(cmd)

    def add_clean(self, cmd):
        self.clean_cmd = cmd

    def write(self):
        with open(self.make_file, "w") as f:
            f.write("SHELL:=/bin/bash\n")
            f.write(".DELETE_ON_ERROR:\n\n")
            f.write("all : ")
            for i in range(len(self.tgts)):
                f.write(f"{self.tgts[i]} ")
            f.write("\n\n")

            for i in range(len(self.tgts)):
                f.write(f"{self.tgts[i]} : {self.deps[i]}\n")
                f.write(f"\t{self.cmds[i]}\n")
                f.write(f"\ttouch {self.tgts[i]}\n\n")

            if self.clean_cmd != "":
                f.write(f"clean : \n")
                f.write(f"\t{self.clean_cmd}\n")


class Sample(object):
    def __init__(self):
        self.idx = ""
        self.id = ""
        self.fastq1 = ""
        self.fastq2 = ""

    def __init__(self, idx, id, fastq1, fastq2):
        self.idx = idx
        self.id = id
        self.fastq1 = fastq1
        self.fastq2 = fastq2

    def print(self):
        print(f"index   : {self.idx}")
        print(f"id      : {self.id}")
        print(f"fastq1  : {self.fastq1}")
        print(f"fastq2  : {self.fastq2}")


class Run(object):
    def __init__(self, id):
        self.idx = id[3::]
        self.id = id
        self.samples = []

    def add_sample(self, idx, sample_id, fastq1, fastq2):
        self.samples.append(Sample(idx, sample_id, fastq1, fastq2))

    def print(self):
        print(f"++++++++++++++++++++")
        print(f"run id       : {self.id}")
        print(f"++++++++++++++++++++")
        for sample in self.samples:
            sample.print()
        print(f"++++++++++++++++++++")


if __name__ == "__main__":
    main()
