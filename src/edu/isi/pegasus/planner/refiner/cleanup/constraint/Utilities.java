/**
 *  Copyright 2007-2015 University Of Southern California
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *  http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing,
 *  software distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */
package edu.isi.pegasus.planner.refiner.cleanup.constraint;

import edu.isi.pegasus.planner.classes.Job;
import edu.isi.pegasus.planner.classes.PegasusFile;
import edu.isi.pegasus.planner.partitioner.graph.Graph;
import edu.isi.pegasus.planner.partitioner.graph.GraphNode;
import org.supercsv.cellprocessor.ParseLong;
import org.supercsv.cellprocessor.ift.CellProcessor;
import org.supercsv.io.CsvBeanReader;
import org.supercsv.prefs.CsvPreference;

import java.io.FileReader;
import java.io.IOException;
import java.io.PrintWriter;
import java.util.*;

/**
 *
 * @author Sudarshan Srinivasan
 * @author Rafael Ferreira da Silva
 */
public class Utilities {

    //Maps from file name to file size
    static Map<String, Long> sizes = null;

    static {
        //TODO: verify the use of the CSV file
        String CSVName = System.getProperty("org.sudarshan.constrainer.csv");
        if (CSVName == null) {
            System.err.println("Falling back to the old mechanism");
        } else {
            try {
                Utilities.loadHashMap(CSVName);
            } catch (IOException e) {
                System.err.println("Falling back to the old mechanism due to IOException");
            }
        }
    }

    static long getFileSize(PegasusFile file) {
        if (sizes == null) {
            return (long) file.getSize();
        }
        System.out.println("SIZES: " + sizes);
        return sizes.get(file.getLFN());
    }

    static String cleanUpJobToString(Iterable<GraphNode> parents, Iterable<GraphNode> heads, Iterable<PegasusFile> listOfFiles) {
        StringBuilder sb = new StringBuilder("CleanupJob{parents = {");
        for (GraphNode parent : parents) {
            sb.append(parent.getID());
            sb.append(',');
        }
        sb.replace(sb.length() - 1, sb.length(), "}, children = {");
        for (GraphNode child : heads) {
            sb.append(child.getID());
            sb.append(',');
        }
        sb.replace(sb.length() - 1, sb.length(), "}, files = {");
        for (PegasusFile file : listOfFiles) {
            sb
                    .append(file.getLFN())
                    .append(':')
                    .append(getFileSize(file))
                    .append(',');
        }
        sb.replace(sb.length() - 1, sb.length(), "}}");
        return sb.toString();
    }

    static void loadHashMap(String csvName) throws IOException {
        final CellProcessor[] processors = new CellProcessor[]{null, null, null, null, new ParseLong()};
        CsvBeanReader beanReader = new CsvBeanReader(new FileReader(csvName), CsvPreference.STANDARD_PREFERENCE);
        final String[] header = beanReader.getHeader(true);
        FileDataBean fileDataBean;
        sizes = new HashMap<String, Long>();
        while ((fileDataBean = beanReader.read(FileDataBean.class, header, processors)) != null) {
            Long currentSize = sizes.get(fileDataBean.filename);
            if (currentSize != null) {
                assert (fileDataBean.length == currentSize);
            }
            sizes.put(fileDataBean.filename, fileDataBean.length);
        }
    }

    static Map<GraphNode, Set<GraphNode>> calculateDependencies(Graph workflow, boolean verbose, PrintWriter logger) {
        //Dependencies is used to map from node to its dependencies
        Map<GraphNode, Set<GraphNode>> dependencies = new HashMap<GraphNode, Set<GraphNode>>();

        //This is our BFS queue
        LinkedList<GraphNode> bfsQueue = new LinkedList<GraphNode>();

        //This is a marker node used to indicate an increase in depth while exploring
        final GraphNode marker = new GraphNode("Marker");

        //Initially, add all root nodes to the BFS queue
        for (GraphNode currentRoot : workflow.getRoots()) {
            bfsQueue.addLast(currentRoot);
        }

        try {
            outer:
            while (true) {
                //Remove one node from the BFS queue
                GraphNode currentNode = bfsQueue.removeFirst();

                //Ensure that the removed node is not already explored
                if (dependencies.containsKey(currentNode)) {
                    continue;
                }

                //Move past any marker nodes we see
                while (currentNode == marker) {
                    currentNode = bfsQueue.removeFirst();
                }

                //Output some extra data if verbose output is on
                if (verbose) {
                    logger.println("Pre analysis of node " + currentNode.getID());
                }

                //Initialise the dependency set for the current node
                Set<GraphNode> currentNodeDependencies = new HashSet<GraphNode>();

                //Iterate over all the parent nodes
                for (GraphNode parent : currentNode.getParents()) {
                    //Ensure that we've already calculated dependencies for this parent node
                    //Otherwise we could end up in trouble here
                    if (!dependencies.containsKey(parent)) {
                        //if we've not yet calculated dependencies for even one of the parents
                        //then push this node sufficiently back in the queue
                        //that we would have calculated all parent dependencies when we return
                        //Basically, push the node to the start of the next level
                        ListIterator<GraphNode> iterator = bfsQueue.listIterator();
                        for (GraphNode searchElement = iterator.next(); iterator.hasNext(); searchElement = iterator.next()) {
                            if (searchElement == marker) {
                                iterator.add(currentNode);
                                break;
                            }
                        }
                        continue outer;
                    }
                    //Update the current node's dependencies
                    currentNodeDependencies.add(parent);
                    currentNodeDependencies.addAll(dependencies.get(parent));
                }

                //Add the current node to the dependencies table
                dependencies.put(currentNode, currentNodeDependencies);

                //Add a marker followed by this node's children
                bfsQueue.add(marker);
                bfsQueue.addAll(currentNode.getChildren());
            }
        } catch (NoSuchElementException e) {
        }
        return dependencies;
    }

    static long getIntermediateRequirement(Job currentJob) {
        long spaceUsed = 0;
        switch (currentJob.getJobType()) {
            case Job.CLEANUP_JOB:
                for (PegasusFile currentFile : (Set<PegasusFile>) currentJob.getInputFiles()) {
                    spaceUsed -= getFileSize(currentFile);
                }
                break;
            case Job.STAGE_OUT_JOB:
                return 0;
            default:
                for (PegasusFile currentFile : (Set<PegasusFile>) currentJob.getOutputFiles()) {
                    spaceUsed += getFileSize(currentFile);
                }
        }
        return spaceUsed;
    }
}
