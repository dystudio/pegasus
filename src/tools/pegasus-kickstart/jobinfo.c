/*
 * This file or a portion of this file is licensed under the terms of
 * the Globus Toolkit Public License, found in file GTPL, or at
 * http://www.globus.org/toolkit/download/license.html. This notice must
 * appear in redistributions of this file, with or without modification.
 *
 * Redistributions of this Software, with or without modification, must
 * reproduce the GTPL in: (1) the Software, or (2) the Documentation or
 * some other similar material which is provided with the Software (if
 * any).
 *
 * Copyright 1999-2004 University of Chicago and The University of
 * Southern California. All rights reserved.
 */
#include <ctype.h>
#include <errno.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>

#include <sys/wait.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>

#include "getif.h"
#include "utils.h"
#include "useinfo.h"
#include "jobinfo.h"
#include "parse.h"
#include "error.h"


int make_application_executable = 0;

static int check_executable(const char* path) {
    /* purpose: check a given file for being accessible and executable
     *          under the currently effective user and group id.
     * paramtr: path (IN): current path to check
     * globals: make_application_executable (IN): if true, chmod to exec
     * returns: 0 if the file is accessible, -1 for not
     */

    /* sanity check */
    if (path == NULL || *path == '\0') {
        errno = ENOENT;
        return -1;
    }

    int result = access(path, R_OK|X_OK);

    if (result != 0 && make_application_executable) {
        struct stat st;
        if (stat(path, &st) != 0) {
            printerr("Unable to stat executable: %s\n", strerror(errno));
            return -1;
        }
        mode_t mode = st.st_mode;
        mode |= (S_IXUSR | S_IRUSR | S_IXGRP | S_IRGRP | S_IXOTH | S_IROTH);
        if (chmod(path, mode) != 0) {
            printerr("Unable to set executable permissions: %s\n", strerror(errno));
            return -1;
        }

        result = access(path, R_OK|X_OK);
    }

    return result;
}

static int isfile(const char *path) {
    /* sanity check */
    if (path == NULL || *path == '\0') {
        errno = ENOENT;
        return 0;
    }

    struct stat st;
    if (stat(path, &st) != 0) {
        return 0;
    }

    if (!S_ISREG(st.st_mode)) {
        /* not a regular file */
        return 0;
    }

    return 1;
}

static char* pathfind(const char* fn) {
    /* purpose: check the executable filename and correct it if necessary
     * paramtr: fn (IN): current knowledge of filename
     * returns: newly allocated fqpn of path to exectuble, or NULL if not found
     */

    /* sanity check */
    if (fn == NULL || *fn == '\0') {
        errno = ENOENT;
        return NULL;
    }

    /* don't touch absolute paths */
    if (fn[0] == '/') {
        if (isfile(fn)) {
            char *exe = strdup(fn);
            if (exe == NULL) {
                printerr("strdup: %s\n", strerror(errno));
                return NULL;
            }
            return exe;
        } else {
            return NULL;
        }
    }

    /* try from CWD */
    if (isfile(fn)) {
        char *exe = strdup(fn);
        if (exe == NULL) {
            printerr("strdup: %s\n", strerror(errno));
            return NULL;
        }
        return exe;
    }

    /* continue only if there is a PATH to check */
    char *s = getenv("PATH");
    if (s == NULL) {
        printerr("PATH not set\n");
        return NULL;
    }

    char *path = strdup(s);
    if (path == NULL) {
        printerr("strdup: %s\n", strerror(errno));
        return NULL;
    }

    char *t = NULL;

    /* tokenize to compare */
    for (s=strtok(path,":"); s; s=strtok(NULL,":")) {
        size_t len = strlen(fn) + strlen(s) + 2;
        t = (char*) malloc(len);
        if (t == NULL) {
            printerr("malloc: %s\n", strerror(errno));
            return NULL;
        }
        strncpy(t, s, len);
        strncat(t, "/", len);
        strncat(t, fn, len);
        if (isfile(t)) {
            break;
        } else {
            free(t);
            t = NULL;
        }
    }

    /* some or no matches found */
    free(path);
    return t;
}
static void __initJobInfo(JobInfo *jobinfo, Node *head, int state) {
    size_t i;
    char* t;

    /* reset everything */
    memset(jobinfo, 0, sizeof(JobInfo));

    /* only continue in ok state AND if there is anything to do */
    if (state == 32 && head) {
        size_t size, argc = size = 0;
        Node* temp = head;
        while (temp) {
            size += (strlen(temp->data) + 1);
            argc++;
            temp = temp->next;
        }

        /* prepare copy area */
        jobinfo->copy = (char*) malloc(size+argc);
        if (jobinfo->copy == NULL) {
            printerr("malloc: %s\n", strerror(errno));
            return;
        }

        /* prepare argument vector */
        jobinfo->argc = argc;
        jobinfo->argv = (char* const*) calloc(argc+1, sizeof(char*));
        if (jobinfo->argv == NULL) {
            printerr("calloc: %s\n", strerror(errno));
            return;
        }

        /* copy list while updating argument vector and freeing lose arguments */
        t = jobinfo->copy;
        for (i=0; i < argc && (temp=head); ++i) {
            /* append string to copy area */
            size_t len = strlen(temp->data)+1;
            memcpy(t, temp->data, len);
            /* I hate nagging compilers which think they know better */
            memcpy((void*) &jobinfo->argv[i], &t, sizeof(char*));
            t += len;

            /* clear parse list while we are at it */
            head = temp->next;
            free((void*) temp->data);
            free((void*) temp);
        }
    }

    /* free list of (partial) argv */
    if (head) {
        deleteNodes(head);
    }

    /* this is a valid (and initialized) entry */
    if (jobinfo->argc > 0) {
        /* check out path to job */
        char* realpath = pathfind(jobinfo->argv[0]);

        if (realpath == NULL || check_executable(realpath) < 0) {
            jobinfo->status = -127;
            jobinfo->saverr = errno;
            jobinfo->isValid = 2;
        } else {
            memcpy((void*) &jobinfo->argv[0], &realpath, sizeof(char*));
            jobinfo->isValid = 1;
        }

        initStatInfoFromName(&jobinfo->executable, jobinfo->argv[0], O_RDONLY, 0);
    }
}

void initJobInfoFromString(JobInfo* jobinfo, const char* commandline) {
    /* purpose: initialize the data structure with default
     * paramtr: jobinfo (OUT): initialized memory block
     *          commandline (IN): commandline concatenated string to separate
     */
    int state = 0;
    Node* head = parseCommandLine(commandline, &state);
    __initJobInfo(jobinfo, head, state);
}

void initJobInfo(JobInfo* jobinfo, int argc, char* const* argv) {
    /* purpose: initialize the data structure with defaults
     * paramtr: jobinfo (OUT): initialized memory block
     *          argc (IN): adjusted argc string (maybe from main())
     *          argv (IN): adjusted argv string to point to executable
     */
    int state = 0;
    Node* head = parseArgVector(argc, argv, &state);
    __initJobInfo(jobinfo, head, state);
}

int printXMLJobInfo(FILE *out, int indent, const char* tag, const JobInfo* job) {
    /* purpose: format the job information into the given stream as XML.
     * paramtr: out (IO): the stream
     *          indent (IN): indentation level
     *          tag (IN): name to use for element tags.
     *          job (IN): job info to print.
     * returns: number of characters put into buffer (buffer length)
     */

    /* sanity check */
    if (!job->isValid) {
        return 0;
    }

    /* start tag with indentation */
    fprintf(out, "%*s<%s start=\"%s\"", indent, "", tag,
            fmtisodate(job->start.tv_sec, job->start.tv_usec));
    fprintf(out, " duration=\"%.3f\"",
            doubletime(job->finish) - doubletime(job->start));

    /* optional attribute: application process id */
    if (job->child != 0) {
        fprintf(out, " pid=\"%d\"", job->child);
    }

    /* finalize open tag of element */
    fprintf(out, ">\n");

    /* <usage> */
    printXMLUseInfo(out, indent+2, "usage", &job->use);

    int status = (int) job->status;

    /* <status>: open tag */
    fprintf(out, "%*s<status raw=\"%d\">", indent+2, "", status);

    /* <status>: cases of completion */
    if (status < 0) {
        /* <failure> */
        fprintf(out, "<failure error=\"%d\">%s%s</failure>", job->saverr,
                job->prefix && job->prefix[0] ? job->prefix : "",
                strerror(job->saverr));
    } else if (WIFEXITED(status)) {
        fprintf(out, "<regular exitcode=\"%d\"/>", WEXITSTATUS(status));
    } else if (WIFSIGNALED(status)) {
        /* result = 128 + WTERMSIG(status); */
        fprintf(out, "<signalled signal=\"%u\"", WTERMSIG(status));
#ifdef WCOREDUMP
        fprintf(out, " corefile=\"%s\"", WCOREDUMP(status) ? "true" : "false");
#endif
        fprintf(out, ">%s</signalled>", sys_siglist[WTERMSIG(status)]);
    } else if (WIFSTOPPED(status)) {
        fprintf(out, "<suspended signal=\"%u\">%s</suspended>", WSTOPSIG(status),
                sys_siglist[WSTOPSIG(status)]);
    } /* FIXME: else? */
    fprintf(out, "</status>\n");

    /* <executable> */
    printXMLStatInfo(out, indent+2, "statcall", NULL, &job->executable, 1);

    /* alternative 1: new-style <argument-vector> */
    fprintf(out, "%*s<argument-vector", indent+2, "");
    if (job->argc == 1) {
        /* empty element */
        fprintf(out, "/>\n");
    } else {
        /* content are the CLI args */
        int i;

        fprintf(out, ">\n");
        for (i=1; i<job->argc; ++i) {
            fprintf(out, "%*s<arg nr=\"%d\">", indent+4, "", i);
            xmlquote(out, job->argv[i], strlen(job->argv[i]));
            fprintf(out, "</arg>\n");
        }

        /* end tag */
        fprintf(out, "%*s</argument-vector>\n", indent+2, "");
    }

    /* <proc>s */
    printXMLProcInfo(out, indent+2, job->children);

    /* finalize close tag of outmost element */
    fprintf(out, "%*s</%s>\n", indent, "", tag);

    return 0;
}

void deleteJobInfo(JobInfo* jobinfo) {
    /* purpose: destructor
     * paramtr: runinfo (IO): valid AppInfo structure to destroy. */
    if (jobinfo == NULL) {
        return;
    }

    if (jobinfo->isValid) {
        if (jobinfo->argv[0] != NULL && jobinfo->argv[0] != jobinfo->copy) {
            free((void*) jobinfo->argv[0]); /* from pathfind() allocation */
        }
        deleteStatInfo(&jobinfo->executable);
    }

    if (jobinfo->copy != NULL) {
        free((void*) jobinfo->copy);
        free((void*) jobinfo->argv);
        jobinfo->copy = 0;
    }

    deleteProcInfo(jobinfo->children);
    jobinfo->children = NULL;

    /* final invalidation */
    jobinfo->isValid = 0;
}

