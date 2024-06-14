This folder contains the distribution of expubcheck project.

ExpubCheck is a tool to validate IDPF Expub files. It can detect many
types of errors in Expub. OCF container structure, OPF and OPS mark-up,
and internal reference consistency are checked. ExpubCheck can be run
as a standalone command-line tool, installed as a web application or
used as a library.

Expubcheck project home: http://code.google.com/p/expubcheck/

BUILDING

To build expubcheck from the sources you need Java Development Kit (JDK) 1.5 or above
and Apache ant (http://ant.apache.org/) 1.6 or above installed

Run

ant -f build.xml

RUNNING

To run the tool you need Java Runtime (1.5 or above). Any OS should do. Run
it from the command line: 

java -jar expubcheck-x.x.x.jar file.expub

All detected errors are simply printed to stderr. 

USING AS A LIBRARY

You can also use ExpubCheck as a library in your Java application. ExpubCheck
public interfaces can be found in com.adobe.expubcheck.api package. ExpubCheck
class can be used to instantiate a validation engine. Use one of its
constructors and then call validate() method. Report is an interface that
you can implement to get a list of the errors and warnings reported by the
validation engine (instead of the error list being printed out).

LICENSING

See COPYING.txt

AUTHORS

Peter Sorotokin 
Garth Conboy 
Markus Gylling 
Piotr Kula

Most of the ExpubCheck functionality comes from the schema validation tool Jing
and schemas that were developed by IDPF and DAISY. ExpubCheck development was
largely done at Adobe Systems. 










