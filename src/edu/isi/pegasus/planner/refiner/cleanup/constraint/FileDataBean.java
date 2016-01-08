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

/**
 *
 * @author Sudarshan Srinivasan
 * @author Rafael Ferreira da Silva
 */
public class FileDataBean {

    public String transformation, id, type, filename;
    public long length;

    public void setTransformation(String transformation) {
        this.transformation = transformation;
    }

    public void setId(String id) {
        this.id = id;
    }

    public void setType(String type) {
        this.type = type;
    }

    public void setFilename(String filename) {
        this.filename = filename;
    }

    public void setLength(long length) {
        this.length = length;
    }

    @Override
    public String toString() {
        return "FileDataBean{"
                + "transformation='" + transformation + '\''
                + ", id='" + id + '\''
                + ", type='" + type + '\''
                + ", filename='" + filename + '\''
                + ", length=" + length
                + '}';
    }
}
